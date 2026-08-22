# START HERE

> **Türkçe hızlı özet:** Bu klasör bir CoreMe çalışma alanıdır. Ajanınıza tek
> cümle yeter: *"AGENTS.md ve START-HERE.md'yi oku; neyi otomatikleştirmek
> istediğimi sor; Job'u kurallara göre yaz, test et, `coreme ship` ile
> dondur ve çalıştır."* Kuralların özü: Job kodu **asla** LLM çağırmaz;
> sırlar yalnızca **isim** olarak bildirilir (değerler ortam değişkeninde);
> her adım olay yazar (`events.jsonl`); çıktılar `artifacts/` altındadır;
> hata maskelenmez. Her başarılı `coreme ship` sonrası commit atılır.

This folder is a **CoreMe workspace**. You (the coding agent reading this)
turn the operator's spoken intent into a proven, frozen, re-runnable Job.
The operator does not type commands. You do.

## 1. Read these first

| File | Why |
|------|-----|
| `AGENTS.md` | Hard rules (never edit `releases/`, secrets names-only, fail-evidence order) |
| `skills/build-job/SKILL.md` | The authoring loop: clarify → contract → code → prove → ship |
| `skills/fleet/SKILL.md` | Only when this machine must join a hub as an unattended worker |

## 2. The Job bar — every Job, every time

A Job is done only when **all six** hold:

1. **Contract spine** — `JOB.md` states goal, inputs, secret names, steps *before* code.
2. **Step events** — every step emits `say_step` events → structured `events.jsonl`; plain `log.txt` stays readable.
3. **Offline proof** — `tests/` with fixture data, zero network, green via `coreme test`.
4. **Phases** — steps ≥ 3 use the phases pattern (`only`/`skip`) for mid-chain debugging.
5. **Artifacts only** — outputs go to `$COREME_ARTIFACTS_DIR`; never litter the cwd.
6. **Honest failure** — real problems exit nonzero and write `fail.json`. Never mask, never retry-until-green inside the Job.

## 3. Working rules

- **Git:** if `.git` is missing run `git init`. Commit after **every successful ship**: `ship <name>-<version>`. Never commit mid-refactor.
- **Secrets:** declare **names** in `JOB.toml`. Values live only in environment variables (`setx NAME value` once, or session `$env:`), set only with the operator's explicit go-ahead. Never write values into files, logs, or evidence.
- **Ship:** `coreme ship ./jobs/<name>` freezes an immutable hashed release. Dirty releases refuse to run — that's the point.
- **Failures:** diagnose in order: `fail.json` → `log.txt` → `events.jsonl`. Fix source, re-prove, re-ship as a new version. Never edit anything under `releases/`.

## 4. Local or fleet?

- **Default: local.** `coreme run ./jobs/<name> --input key=value` — evidence lands in `runs/<job>-<timestamp>/`.
- **Fleet** (unattended / scheduled / other PCs): enroll this machine to the operator's hub — recipe in `skills/fleet/SKILL.md` (`coreme-agent enroll --hub URL --token ...`, then `coreme-agent run`). Ask the operator for hub URL + enroll token first.

## 5. Definition of done

- [ ] Intent clarified with the operator; inputs are declared parameters, not chat memory
- [ ] `JOB.md` written; six-point bar holds
- [ ] `coreme test` green offline
- [ ] Live `coreme run` succeeded OR failed honestly with diagnosed cause
- [ ] `coreme ship` frozen + committed
- [ ] Operator told: Job path, Run path, how to re-run tomorrow without you

## 6. Health check

Anything odd? `coreme doctor [--hub URL]` self-checks python, deps, this
workspace (agent docs, git), and hub reachability. Machine-readable:
`coreme doctor --json`.
