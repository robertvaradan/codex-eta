# ETA for Codex desktop

ETA is a small, draggable Windows companion timer for Codex. It starts when a
Codex turn receives your prompt, adjusts its remaining-time estimate every
second, and learns from completed turns on the same model and task category.
The history stays in a local SQLite database under Codex's `PLUGIN_DATA`
directory. Prompt text is **not** stored.

This is an estimate, not a deadline. ETA predicts the end of the current Codex
turn, because Codex hooks expose prompt submission and turn stop events. A
larger task may need several turns. Codex does not offer a plugin slot beside
the model indicator, so ETA uses a separate always-on-top window. Drag it to
the desired position beside Codex.

## Requirements

- Windows 10/11 and the Codex desktop app
- Python 3.10+ available as `python` on PATH, with Tkinter (`python -m tkinter`)
- Trust the plugin's three local lifecycle hooks when Codex asks

There are no third-party Python dependencies. Hook errors are visible as hook
failures; ETA does not alter task prompts or gate Codex execution.

## Install from this GitHub marketplace

1. Run `codex plugin marketplace add robertvaradan/codex-eta`, or clone this
   repository and run
   `codex plugin marketplace add <path-to-clone>`.
2. Run `codex plugin add eta@eta-local`. Restart Codex desktop.
3. Use `/hooks` in the Codex CLI to review and trust ETA's three hooks. Start a
   new Codex desktop chat and send a prompt.
4. The companion window opens after the first prompt. Drag it near the model
   indicator. The × button closes it until the next prompt.

The hooks use `UserPromptSubmit`, `Stop`, and `Interrupt` to track turns. A
completed turn contributes to local history; an interrupted turn does not.
With no history, ETA starts from documented category priors: 75 seconds for
short requests, 5 minutes for research, 7 minutes for coding, and 15 minutes
for large requests. The category is derived from simple words and prompt length.
After matching completed turns, their durations gradually replace that prior.
The live estimate is the median remaining time conditional on the turn still
running, so it can rise when work takes longer than expected.

## Privacy and data

ETA stores session/turn IDs, model ID, task category, start/end timestamps,
and outcome locally. It does not transmit data or store prompt bodies. Remove
`eta.sqlite3` from the plugin data directory to reset learning. The companion
window only reads the same local database.

## Development

Run `python -m unittest discover -s tests -v` from this repository. To exercise
the hook manually, set `PLUGIN_DATA` to a temporary directory and pipe a JSON
`UserPromptSubmit` event into `plugins/eta/hooks/eta_hook.py`. This opens the
companion window. Send a matching `Stop` event to finish the turn.

## Publishing

The GitHub marketplace in this repository is suitable for local or team
distribution. [OpenAI's current plugin packaging guide](https://developers.openai.com/plugins/build/plugins)
says packages with lifecycle hooks are not eligible for the universal public
Plugin Directory. The [submission guide](https://developers.openai.com/plugins/deploy/submission)
also says to remove hooks before public submission. Removing them would remove
ETA's automatic timing, so this version should stay in a Git-backed marketplace
until Codex offers a supported public route for this desktop behavior.
