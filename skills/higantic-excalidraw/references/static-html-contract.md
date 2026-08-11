# Canvas scene contract

This filename is retained for compatibility with the shared public-skill release validator. It defines an Excalidraw Canvas contract; it does not authorize or produce HTML.

Prefer semantic flowchart input for workflows and process maps. The server owns geometry, stage color, connector routing, arrow binding, and validation. Use raw scene JSON only when the request requires geometry that semantic input cannot express or when preserving an existing scene.

All writes remain private workspace content. Read before replacement, send the observed scene version, reconcile conflicts, and require explicit confirmation before deletion. Never put credentials, secrets, or private source excerpts into labels or scene metadata.
