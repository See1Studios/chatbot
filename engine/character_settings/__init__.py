"""Character settings (docs/plans/character-settings.md): every setting of a character in one place, for the profile
drawer to show and edit. The server lists each one as a schema entry and merges a change into its own file; every
write keeps the file's previous version for restore (personalization-ladder ladder/B and ladder/C, character layer).

  fields.py   what there is: key, tab, type, label, source, editable, sensitive (the one list)
  store.py    read them, merge changes into their files with a version kept, list and restore versions, the HTTP API
"""
