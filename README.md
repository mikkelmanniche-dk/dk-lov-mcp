# dk-lov-mcp

Dansk lov fra [Retsinformation](https://www.retsinformation.dk) som MCP-server. Giv Claude, Cursor
eller en anden MCP-klient adgang til at slå love op på navn, søge i fritekst og citere den ordrette
paragraftekst med ELI-link, så svaret kan efterprøves.

*English: an MCP server for Danish law. It looks up acts by name or free text, returns the verbatim
text of a section with its official ELI link, and flags amending acts that are not yet consolidated.*

## Hvad den kan

| Værktøj | Hvad |
|---|---|
| `lov_register` | Ofte brugte love med faste navne og forkortelser (`OFL`, `ÅRL`, `CVR-loven` …) |
| `lov_soeg` | Fritekstsøgning, som på retsinformation.dk |
| `lov_hent` | Titel, status, ELI, citat og senere ændringer |
| `lov_paragraf` | Ordret tekst for én paragraf eller ét stykke |
| `lov_tekst` | Hele teksten uden XML |
| `lov_aendringer` | Dokumenter ændret på en dato |

`lov` kan være et navn (`offentlighedsloven`, `OFL`), en dansk henvisning
(`LBK nr. 145 af 24/02/2020`) eller et ELI-link.

Hvert svar har `citat` (fx "Bekendtgørelse af årsregnskabsloven (LBK nr. 402 af 23/03/2026)") og
`eli`. `gaeldende: false` betyder, at dokumentet er historisk. `senere_aendringer` viser
ændringslove, som endnu ikke er skrevet ind i den samlede tekst, så paragrafteksten kan være
forældet. Serveren siger det selv i `advarsel`.

## Installation

Kræver [uv](https://docs.astral.sh/uv/). Claude Code:

```
claude mcp add dk-lov -- uvx --from git+https://github.com/mikkelmanniche-dk/dk-lov-mcp dk-lov-mcp
```

Andre klienter (Claude Desktop, Cursor …):

```json
{
  "mcpServers": {
    "dk-lov": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/mikkelmanniche-dk/dk-lov-mcp", "dk-lov-mcp"]
    }
  }
}
```

Ingen nøgle eller konto. Data hentes fra Retsinformations åbne API og gemmes i en lokal cache.

## Begrænsninger

- Kun det, der står i Retsinformation. Domstolspraksis, forarbejder og EU-forordninger (fx GDPR)
  er der ikke.
- Teksten er ordret, men serveren giver ikke juridisk rådgivning.
- `lov_aendringer` virker kun i Retsinformations åbningstid (03:00–23:45).

## Udvikling

```
uv run pytest                 # offline mod tests/fixtures
DK_LOV_LIVE=1 uv run pytest   # også mod Retsinformation
```

Lovregistret ligger i `src/dk_lov_mcp/love.json`.

## Licens

Apache-2.0. Fork af [matematicsolutions/dk-eli-mcp](https://github.com/matematicsolutions/dk-eli-mcp);
se `NOTICE` for ændringerne. Lovtekst er ikke omfattet af ophavsret (ophavsretsloven § 9).
