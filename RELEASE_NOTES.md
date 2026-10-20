<!-- release: v2.12.1438 -->

## What's Changed

**SolarEdge live power readings**
PowerSync now detects stale SolarEdge readings instead of continuing to show old solar generation or grid export as current. Readings older than two minutes pause energy accounting and automatic controls that need live data, and normal operation resumes when fresh reports arrive.

If readings become unavailable, check the connection and polling health of the SolarEdge integration in Home Assistant.

Update available via HACS
