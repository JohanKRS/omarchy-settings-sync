# Opening performance

The panel is built when first requested. No conversation or configuration sync
starts just because it opens. Model metadata can refresh in the background.

After an idle close, the interface stays in memory for up to 60 seconds. A new
open request reaches that existing process through D-Bus, avoiding another GTK
import and widget build. After the timeout, it exits. An active task, embedded
CLI or pending question keeps its process alive as before.

Idle agent connections close in a worker so hiding the panel does not wait for
CLI shutdown. If the same conversation resumes immediately, the new worker waits
for the previous connection to close before starting another. Theme polling pauses
while hidden and refreshes on reopening. The VTE widget and typelib are loaded
only for an embedded CLI. The launcher checks installed dependencies without a
second GTK import on the cold path.

## Local measurements

Five samples on the same Omarchy 4.0.5-1 desktop, Python 3.14.8:

| Build and operation | Median to first frame |
| --- | ---: |
| Previous build, new application | 285.8 ms |
| Prepared build, new application | 293.2 ms |
| Prepared build, reopen within retention period | 13.7 ms |

The measured improvement is in repeated opening: about 95% less time than
starting a new application. The fresh application measurements are effectively
unchanged. The cold benchmark starts the application directly and excludes shell
launcher dependency checks; it does not measure any improvement from removing the
old redundant GTK preflight import. Agent response and model discovery latency
are also outside this measurement.

The benchmark records the first GTK frame callback after mapping the window,
not a camera measurement of screen presentation. Results depend on the machine,
display refresh rate, compositor and current load. The temporary warm interface
uses additional memory while retained; there is no permanent background service.

## Reproduce

Run in an Omarchy desktop session with the panel dependencies installed:

```sh
python3 tools/benchmark_open.py --samples 5
python3 tools/benchmark_open.py --source /path/to/older/checkout --samples 5 --cold-only
```

The tool uses temporary settings, separate application IDs and an example
repository. It neither changes the real configuration nor starts an agent task.
It closes only its own benchmark processes afterward.
