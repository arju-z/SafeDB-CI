#!/bin/sh -l

echo "Hello $INPUT_WHO_TO_GREET"
time=$(date)
echo "time=$time" >> $GITHUB_OUTPUT
