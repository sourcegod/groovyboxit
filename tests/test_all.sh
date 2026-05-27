#!/bin/bash
### Run all python tests
### Date: Wed, 27/05/2026
### Author: Coolbrother


for f in tests/test_*.py; do 
    echo "=== $f ==="; python3 "$f" 2>&1; echo;

done

exit 0
