#!/usr/bin/env bash

curl -X POST -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiI5OGE5ZmVmNjE0YTQ0YzgyODUwNTY1ZjZmZWI2NmMyYSIsImlhdCI6MTY5NzE2NjQ5NSwiZXhwIjoyMDEyNTI2NDk1fQ.EQsvrGC8VTokwPNRNHU9OKarE_IXnw4s8lAXLzZ-1SA" -H "Content-Type: application/json" -d '{"entity_id": "switch.securifi_ltd_unk_model_switch"}' https://8088.org:8123/api/services/switch/turn_off
