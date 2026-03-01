#!/bin/bash

# Source icon (change this to your icon path)
SOURCE_ICON="web/icons/icon-192.png"

# Target icons directory
TARGET_DIR="web/icons"

# Generate icons of different sizes
convert "$SOURCE_ICON" -resize 72x72 "$TARGET_DIR/icon-72x72.png"
convert "$SOURCE_ICON" -resize 96x96 "$TARGET_DIR/icon-96x96.png"
convert "$SOURCE_ICON" -resize 128x128 "$TARGET_DIR/icon-128x128.png"
convert "$SOURCE_ICON" -resize 144x144 "$TARGET_DIR/icon-144x144.png"
convert "$SOURCE_ICON" -resize 152x152 "$TARGET_DIR/icon-152x152.png"
convert "$SOURCE_ICON" -resize 180x180 "$TARGET_DIR/apple-touch-icon.png"
convert "$SOURCE_ICON" -resize 192x192 "$TARGET_DIR/icon-192x192.png"
convert "$SOURCE_ICON" -resize 384x384 "$TARGET_DIR/icon-384x384.png"
convert "$SOURCE_ICON" -resize 512x512 "$TARGET_DIR/icon-512x512.png"
convert "$SOURCE_ICON" -resize 32x32 "$TARGET_DIR/favicon-32x32.png"
convert "$SOURCE_ICON" -resize 16x16 "$TARGET_DIR/favicon-16x16.png"

echo "Icons generated successfully in $TARGET_DIR"