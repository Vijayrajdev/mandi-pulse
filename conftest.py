"""Root pytest config.

Its location matters: because this file sits in the project root, pytest adds the root
to sys.path, so tests can `import ingestion...` with a plain `pytest` command
(no installable package needed).
"""
