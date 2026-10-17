"""ARQ settings for AC-009's deterministic two-worker overlap check."""

from app.worker import WorkerSettings as ApplicationWorkerSettings


class WorkerSettings(ApplicationWorkerSettings):
    # ARQ intentionally reads only the concrete class's __dict__, so re-export
    # the application settings the same way the production settings class does.
    functions = ApplicationWorkerSettings.functions
    on_startup = ApplicationWorkerSettings.on_startup
    on_shutdown = ApplicationWorkerSettings.on_shutdown
    redis_settings = ApplicationWorkerSettings.redis_settings
    job_timeout = ApplicationWorkerSettings.job_timeout
    max_tries = ApplicationWorkerSettings.max_tries
    keep_result = ApplicationWorkerSettings.keep_result
    queue_read_limit = ApplicationWorkerSettings.queue_read_limit
    cron_jobs = ApplicationWorkerSettings.cron_jobs

    # Keep one in-flight job per process so two roots can be observed on two
    # independent worker IDs while the browser holds the same-second boundary.
    max_jobs = 1
