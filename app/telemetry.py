"""KPI-1 to KPI-5 and the approver audit, as Application Insights custom events (ADR-016)."""

import logging
from os import environ

from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor

LOGGER = logging.getLogger("trainyard")
LOGGER.setLevel(logging.INFO)


def configure() -> None:
    if "APPLICATIONINSIGHTS_CONNECTION_STRING" in environ:
        configure_azure_monitor(
            credential=DefaultAzureCredential(), logger_name=LOGGER.name, enable_trace_based_sampling_for_logs=False
        )


def event(name: str, **properties: object) -> None:
    kept = {key: value for key, value in properties.items() if value is not None}
    LOGGER.info(name, extra={"microsoft.custom_event.name": name} | kept)
