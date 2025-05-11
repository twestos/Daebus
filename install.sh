#!/bin/bash
set -e

# Install daebus from the current directory to the system
echo "Installing daebus to /home/pi/software/libraries/daebus"

# Get current directory and target directory
CURRENT_DIR=$(pwd)
TARGET_DIR="/home/pi/software/libraries/Daebus"

# Create target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

# Only copy files if we're not already in the target directory
if [ "$(realpath "$CURRENT_DIR")" != "$(realpath "$TARGET_DIR")" ]; then
  echo "Copying files from $CURRENT_DIR to $TARGET_DIR"
  cp -r * "$TARGET_DIR/"
else
  echo "Already in target directory, skipping copy"
fi

# Change to the target directory (this is a no-op if we're already there)
cd "$TARGET_DIR"

# Create proper package structure
echo "Creating proper package structure..."
mkdir -p daebus
# Check if Python files need to be moved
if [ -f "__init__.py" ] && [ ! -f "daebus/__init__.py" ]; then
  # Move Python files into the package subdirectory
  mv __init__.py daebus/
fi

# We should already be in a virtual environment from the main install.sh
# This is just a safety check
if [ -z "${VIRTUAL_ENV:-}" ]; then
    echo "Warning: Not running in a virtual environment."
    echo "This may cause installation errors due to PEP 668 restrictions."
    echo "Continuing anyway, but installation may fail."
fi

# Install the package with PEP 517 build
pip install --use-pep517 -e .

echo "daebus installed successfully!"
echo "You can import it with: import daebus as bs" 