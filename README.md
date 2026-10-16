# ETA for Codex desktop

The Codex agent supplies its estimate of time remaining. ETA displays it in a
small, draggable Windows companion window, asks the agent to revise it as work
progresses, and calibrates future estimates using locally measured errors.

ETA predicts the time until the agent's final response for the current turn.
A larger task may need several turns. Codex does not offer a plugin slot beside
the model indicator, so the window is separate and always on top. Drag it to
the desired position beside Codex.

## How predictions work

1. **Ask the agent.** A `UserPromptSubmit` hook starts the local turn record and
   provides instructions for the primary agent to report its expected remaining
   wall-clock seconds after reading the request and forming an initial plan.
   The estimate includes expected tool waits, implementation, verification,
   and final reporting. The agent also chooses the task category.
2. **Show its estimate.** The agent runs the bundled `eta_report.py` command
   using its shell tool. The hook supplies the exact command, data directory,
   session ID, and turn ID. The companion reads that record and counts down
   once per second. It shows **Waiting for agent ETA** before the first report.
3. **Get revisions.** The agent is instructed to revise its estimate at phase
   changes or when unexpected work appears. A `PostToolUse` hook provides a
   reminder when at least a minute has passed since the last estimate. Reminders
   occur at tool boundaries and cannot wake the agent while it is waiting on
   a long tool call. The window shows **Awaiting revised ETA** when a prediction
   expires; it does not invent a replacement time.
4. **Learn from errors.** `Stop` records the actual finish time. The next
   matching estimate gets a correction based on actual remaining time divided
   by the agent's original predicted remaining time. Each completed turn gets
   one vote, using its first estimate. Interrupted turns and old history with
   no agent estimate do not train the correction.

Calibration uses up to 100 completed turns for the same model and agent-chosen
category. It takes the geometric actual/predicted ratio, shrinks it toward 1
with four neutral observations, and bounds the correction to 0.25–4. For example,
if the agent tends to predict two minutes and actually needs four, the displayed
time gradually adjusts upward. With no paired history, ETA shows the agent's
estimate unchanged. The window labels a correction as `agent × 1.20`, for example.

This does not query another model or read private reasoning. It asks the working
agent through Codex's supported hook context, and that agent reports through a
local command. Reports use shell tool calls, so they add a small amount of work.
Instruction following is required: if the agent skips a report, the window
explicitly waits. Immediate final answers need no estimate.

## Requirements

- Windows 10/11 and the Codex desktop app, with local execution
- Python 3.10+ available as `python` on PATH, with Tkinter (`python -m tkinter`)
- Trust the plugin's lifecycle hooks when Codex asks

There are no third-party Python dependencies. Hook/report errors are surfaced;
ETA does not gate task execution. The agent receives concise timing instructions
and periodic reminders through hook output.

## Install from this GitHub marketplace

1. Run `codex plugin marketplace add robertvaradan/codex-eta`.
2. Run `codex plugin add eta@eta-local`. Restart Codex desktop.
3. Review and trust ETA's hooks in Codex's Hooks settings (or `/hooks` in the
   Codex CLI). Match the **eta@eta-local** source:
   - `UserPromptSubmit`: start the turn and request an estimate
   - `PostToolUse`: remind the agent to revise its estimate
   - `Stop`: record actual completion
   - `Interrupt`: clear a cancelled turn and exclude it from learning
4. Start a new desktop chat and send a request requiring work. The companion
   opens immediately and waits for the agent's first estimate. Drag it beside
   the model indicator. The × button closes it until the next prompt.

If your client's hook browser does not show `Interrupt`, cancellation cleanup
is not configured there; a cancelled turn can remain visible. Ordinary starts
and finishes use the other hooks. Do not mark unrelated hooks trusted for ETA.

To update an existing installation:

```powershell
codex plugin marketplace upgrade eta-local
codex plugin add eta@eta-local
```

Restart Codex and review changed hooks. Version 0.2 changes hook commands and
adds `PostToolUse`, so old trust entries do not authorize the revised hooks.

## Privacy and data

ETA stores session/turn IDs, model ID, agent-chosen category, start/end times,
outcome, agent time estimates, and applied calibration locally in SQLite under
Codex's `PLUGIN_DATA` directory. It does not store prompts, task descriptions,
or reasoning, and has no network code. Old v0.1 duration history is preserved
but excluded from calibration because it has no corresponding agent estimates.

Close the companion before removing `eta.sqlite3` from the plugin data directory
to reset learning. Window startup errors are recorded in `eta-window.log` there.

## Development

Run `python -m unittest discover -s tests -v` from this repository. To exercise
the hook manually, set `PLUGIN_ROOT` to `plugins/eta` and `PLUGIN_DATA` to a
temporary directory. Pipe a JSON `UserPromptSubmit` event into the configured
hook command. Use the reporting command from its `additionalContext` to supply
an estimate, then send a matching `Stop` event to finish the turn. Use synthetic
IDs and an isolated data directory for testing.

## Publishing

This repository is a Git-backed marketplace for local or team distribution.
[OpenAI's packaging guide](https://developers.openai.com/plugins/build/plugins)
and [submission guide](https://developers.openai.com/plugins/deploy/submission)
say plugins containing lifecycle hooks cannot currently enter the universal
public Plugin Directory. This version depends on those hooks and should be
distributed through this Git-backed marketplace until OpenAI supports that
desktop behavior in the public directory.
