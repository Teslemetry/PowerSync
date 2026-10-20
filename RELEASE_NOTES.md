<!-- release: v2.12.1444 -->

## Improved

### More time for local AI explanations

Ollama, Open WebUI and other local AI servers now have 120 seconds to generate a plan explanation by default. Set **Local AI timeout (seconds)** from 30 to 600 seconds in the explanation card’s settings or the integration’s AI explanation options; the card waits for the selected duration, including any compatibility retry.

After updating, restart Home Assistant and reload the dashboard to load the new setting. Reasoning and effort options remain controlled by your local server.
