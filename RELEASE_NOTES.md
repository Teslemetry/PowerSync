<!-- release: v2.12.1402 -->

## What's Changed

**Use your ChatGPT plan for AI Plan Explanations**
Administrators can now connect an eligible ChatGPT account from the AI Plan Explanation card's settings. Select ChatGPT, open the OpenAI sign-in page, approve the connection, then paste the final redirect address back into the card. The redirect points to a local callback address, so that browser tab may show a connection error; the card explains how to complete sign-in and checks that the address belongs to the pending session. Once connected, the card shows the account and offers models from its available subscription catalog.

**OpenAI API keys and provider settings in the card**
The card also supports OpenAI with an API key and a configurable model, alongside Gemini, Grok, OpenRouter and local OpenAI-compatible providers. OpenAI API usage is billed separately from a ChatGPT plan. Administrators can manage provider settings, replace or remove a saved API key, reconnect ChatGPT and log out from the card. The dashboard asset version is updated so Home Assistant loads the new controls.

**Private credentials and connection recovery**
ChatGPT credentials are stored separately for each PowerSync config entry in a private Home Assistant store, with automatic token refresh. Callback validation, administrator checks and account verification protect the sign-in flow. Temporary network or provider errors show a retry message; expired or rejected credentials prompt reconnection. The card checks the resulting connection state when a request's outcome is uncertain, and credential recovery preserves a newer in-memory grant across an integration reload when storage is temporarily unavailable.

**Clear logout and explanation status**
Logout and integration removal attempt to revoke the remote connection and remove local credentials. If remote revocation cannot be confirmed, PowerSync asks you to disconnect the app in ChatGPT settings. Explanation requests report usage limits, interrupted responses and unavailable providers without displaying credentials or provider error bodies. AI Plan Explanations remain descriptive: the deterministic optimizer and existing hardware controls continue to own the energy plan.

Update available via HACS
