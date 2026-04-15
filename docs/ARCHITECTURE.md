# MeshBridge Architecture

## Overview

MeshBridge is built around a single internal message object.

The design goal is:
- ingress creates one canonical object
- later stages enrich it
- delivery sends it
- neighbor tracking and diagnostics read from it

## Core flow

### Discord -> Mesh
1. Discord message arrives in a mapped channel
2. Bot creates a `BridgeMessage`
3. Message is queued
4. Route/rate-limit checks are applied
5. Text is prefixed with the Discord display name
6. Text is chunked for MeshCore if needed
7. Message is sent to the mapped mesh channel

### Mesh -> Discord
1. MeshCore event arrives
2. Bridge creates a `BridgeMessage`
3. Sender, RF, path, and route metadata are extracted
4. Neighbor store is updated from the message
5. Message is queued
6. Route/rate-limit checks are applied
7. Webhook sends the message using the Mesh node name as the Discord display name
8. Message body is sent as plain text only

## Message object

The canonical message object stores:
- source
- kind
- created timestamp
- text
- sender info
- route info
- path info
- RF info
- metadata
- delivery status
- history notes

## Neighbor model

Neighbors are tracked separately from message history.

The bridge:
- uses a canonical short key prefix for indexing
- seeds records from adverts/path events
- upgrades records from later messages
- optionally enriches names from contact lookup when supported
- persists only a small compact cache to disk

## Memory strategy

The bridge avoids unbounded memory growth by:
- using bounded in-memory message history
- keeping neighbor persistence compact
- not storing large raw upstream library objects in history
- trimming old in-memory message objects automatically

## Security model

Bridged messages are always treated as plain text data.

The bridge does **not**:
- execute commands from bridged message content
- fetch URLs from bridged message content
- render HTML
- render custom markup
- allow untrusted avatars for Mesh-originated webhook posts

Sensitive control actions are restricted to Discord slash commands from users with the Administrator permission.
