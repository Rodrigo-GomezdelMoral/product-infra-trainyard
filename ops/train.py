"""REQ-02: the delivery workflows submit the training pipeline with the components registered for their image."""

import argparse

from azure.ai.ml import MLClient
from azure.ai.ml.exceptions import ValidationErrorType, ValidationException
from azure.identity import AzureCliCredential

from ml.pipeline import submit

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="ops.train")
    for name in ("subscription", "group", "workspace", "endpoint", "version", "identity"):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    client = MLClient(AzureCliCredential(), args.subscription, args.group, args.workspace)
    try:
        print(submit(client, args.endpoint, args.version, args.identity))
    except ValidationException as missing:
        if missing.error_type != ValidationErrorType.RESOURCE_NOT_FOUND:
            raise
        print("No pipeline was submitted: there is no fleet feed yet; seed it with the feed operation (ADR-012).")
