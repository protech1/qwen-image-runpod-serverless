#!/usr/bin/env python3
"""Validate workflow templates offline; optionally prepare or send a real job.

  python scripts/test_endpoint.py
  python scripts/test_endpoint.py --dry-run examples/request-turbo.json
  RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... python scripts/test_endpoint.py --live examples/request-turbo.json

--live is the only mode that invokes a billable endpoint; no GPU calls by default.
"""

import argparse
import json
import sys

from generate import JobError, run_job
from prepare_request import RequestError, WORKFLOW_NAMES, WORKFLOWS, load_plain_request, load_workflow, prepare_request


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", metavar="REQUEST_JSON", help="Print worker payload without network access")
    mode.add_argument("--live", metavar="REQUEST_JSON", help="Submit one billable asynchronous job")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--max-wait", type=float, default=900)
    args = parser.parse_args(argv)
    try:
        validated = []
        edit_files = [WORKFLOWS / name for (_, editing), name in WORKFLOW_NAMES.items() if editing]
        if any(path.exists() for path in edit_files) and not all(path.exists() for path in edit_files):
            raise RequestError("Both normal and turbo edit workflows must be installed together")
        for (turbo, editing), filename in WORKFLOW_NAMES.items():
            if editing and not (WORKFLOWS / filename).exists():
                continue  # Edit workflows are optional.
            load_workflow(turbo, editing)
            validated.append(filename)
        if args.dry_run or args.live:
            request = load_plain_request(args.dry_run or args.live)
            if args.dry_run:
                print(json.dumps(prepare_request(request), indent=2))
            else:
                if args.max_wait <= 0:
                    raise RequestError("--max-wait must be positive")
                print(json.dumps(run_job(request, output_dir=args.output_dir,
                                         max_wait=args.max_wait)))
        else:
            print(json.dumps({"validated_workflows": validated, "network_requests": 0}))
        return 0
    except (RequestError, JobError) as exc:
        print(json.dumps({"error": str(exc), "type": "request_error" if isinstance(exc, RequestError)
                          else "job_error"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
