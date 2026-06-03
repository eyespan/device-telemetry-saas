#!/bin/bash
# 1. Create and activate virtual environment
#python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
#pip install awsiotsdk requests

# 3. Run the test
python3 test_api_throttle.py

# 4. Deactivate when done
deactivate

