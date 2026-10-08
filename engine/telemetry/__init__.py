"""Telemetry: the log system (docs/plans/telemetry.md). What happened on this host, written once and read many ways.

  obslog.py      writing: one JSON line per event (format, redaction, storm guard, rotation) -- OBSLOG_v1
  archive.py     history: rotated files gzipped and kept KEEP_DAYS (tl/B)
  logdigest.py   reading: the window digest and its findings, timelines, the `chatbot-ctl.sh logs` CLI
"""
