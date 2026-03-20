"""
IngestionScheduler - wires APScheduler cron jobs for each data source.

Jobs:
  daily_eod      18:00 ET Mon-Fri  →  EOD OHLCV + macro + options snapshot
  intraday       Every 15min during market hours  →  intraday OHLCV bars
  macro_weekly   Saturday 06:00  →  full FRED backfill for the past week
"""
from datetime import date, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from quantpulse_ingestion.config import settings
from quantpulse_ingestion.fetchers.macro import MacroFetcher
from quantpulse_ingestion.fetchers.ohlcv import OHLCVFetcher
from quantpulse_ingestion.fetchers.options import OptionsFetcher
from quantpulse_ingestion.publisher import KafkaPublisher
from quantpulse_ingestion.writer import DBWriter

logger = structlog.get_logger(__name__)


class IngestionScheduler:
    def __init__(
        self,
        publisher: KafkaPublisher,
        writer: DBWriter,
    ) -> None:
        self.publisher = publisher
        self.writer = writer
        self.ohlcv_fetcher = OHLCVFetcher()
        self.macro_fetcher = MacroFetcher()
        self.options_fetcher = OptionsFetcher()
        self._scheduler = AsyncIOScheduler(timezone="America/New_York")
        self.log = structlog.get_logger(self.__class__.__name__)

    def start(self) -> None:
        # Daily EOD - runs after market close
        self._scheduler.add_job(
            self.run_eod_ingestion,
            CronTrigger.from_crontab(settings.ingest_cron_daily, timezone="America/New_York"),
            id="daily_eod",
            name="Daily EOD ingestion",
            max_instances=1,
            misfire_grace_time=3600,
        )
        # Intraday OHLCV during market hours
        self._scheduler.add_job(
            self.run_intraday_ingestion,
            CronTrigger.from_crontab(settings.ingest_cron_intraday, timezone="America/New_York"),
            id="intraday",
            name="Intraday 15-min ingestion",
            max_instances=1,
            misfire_grace_time=300,
        )
        # Weekly macro backfill (Saturday morning)
        self._scheduler.add_job(
            self.run_macro_backfill,
            CronTrigger(day_of_week="sat", hour=6, timezone="America/New_York"),
            id="macro_weekly",
            name="Weekly macro backfill",
            max_instances=1,
        )
        self._scheduler.start()
        self.log.info("scheduler_started", jobs=len(self._scheduler.get_jobs()))

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)

    # ── Jobs ─────────────────────────────────────────────────────────────────

    async def run_eod_ingestion(self) -> None:
        """Full EOD pipeline: OHLCV → options → macro → publish + write."""
        today = date.today()
        start = today - timedelta(days=5)   # fetch last 5 days to catch gaps
        self.log.info("eod_ingestion_start", date=str(today))

        # 1. OHLCV
        ohlcv_by_ticker = await self.ohlcv_fetcher.fetch_universe(
            settings.tickers, start=start, end=today, interval="1d"
        )
        all_ohlcv = [r for records in ohlcv_by_ticker.values() for r in records]
        if all_ohlcv:
            await self.publisher.publish_ohlcv(all_ohlcv)
            await self.writer.write_ohlcv(all_ohlcv)

        # 2. Options snapshot (derived metrics published alongside OHLCV batch)
        options_metrics = await self.options_fetcher.fetch_universe_options(settings.tickers)
        self.log.info("options_metrics_fetched", tickers=len(options_metrics))
        # Options metrics are passed to the feature service via a separate Kafka message
        # (published as enrichment metadata on the raw-ohlcv topic)

        # 3. Macro
        macro_records = await self.macro_fetcher.fetch_all_series(start=start, end=today)
        if macro_records:
            await self.publisher.publish_macro(macro_records)
            await self.writer.write_macro(macro_records)

        self.log.info(
            "eod_ingestion_complete",
            ohlcv_records=len(all_ohlcv),
            macro_records=len(macro_records),
        )

    async def run_intraday_ingestion(self) -> None:
        """15-minute intraday bars for all tickers."""
        today = date.today()
        self.log.info("intraday_ingestion_start")

        ohlcv_by_ticker = await self.ohlcv_fetcher.fetch_universe(
            settings.tickers, start=today, end=today, interval="15m"
        )
        all_ohlcv = [r for records in ohlcv_by_ticker.values() for r in records]
        if all_ohlcv:
            await self.publisher.publish_ohlcv(all_ohlcv)
            await self.writer.write_ohlcv(all_ohlcv)

        self.log.info("intraday_ingestion_complete", records=len(all_ohlcv))

    async def run_macro_backfill(self) -> None:
        """Weekly FRED backfill for the past 7 days."""
        end = date.today()
        start = end - timedelta(days=7)
        self.log.info("macro_backfill_start", start=str(start), end=str(end))

        macro_records = await self.macro_fetcher.fetch_all_series(start=start, end=end)
        if macro_records:
            await self.publisher.publish_macro(macro_records)
            await self.writer.write_macro(macro_records)

        self.log.info("macro_backfill_complete", records=len(macro_records))

    async def run_historical_backfill(self, years: int = 5) -> None:
        """
        One-time historical backfill - call manually via the REST endpoint.
        Fetches N years of daily OHLCV and macro data.
        """
        end = date.today()
        start = date(end.year - years, end.month, end.day)
        self.log.info("historical_backfill_start", start=str(start), end=str(end), years=years)

        # Macro first - feature consumer caches macro so subsequent OHLCV flushes have it
        macro_records = await self.macro_fetcher.fetch_all_series(start=start, end=end)
        if macro_records:
            await self.writer.write_macro(macro_records)
            await self.publisher.publish_macro(macro_records)

        # OHLCV - published per-ticker so each message stays well under 1 MB
        ohlcv_by_ticker = await self.ohlcv_fetcher.fetch_universe(
            settings.tickers, start=start, end=end, interval="1d"
        )
        all_ohlcv = [r for records in ohlcv_by_ticker.values() for r in records]
        if all_ohlcv:
            await self.writer.write_ohlcv(all_ohlcv)
            for ticker_records in ohlcv_by_ticker.values():
                if ticker_records:
                    await self.publisher.publish_ohlcv(ticker_records)

        self.log.info(
            "historical_backfill_complete",
            ohlcv=len(all_ohlcv),
            macro=len(macro_records),
        )
