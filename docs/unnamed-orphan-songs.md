# Songs on disk with no catalogue row

_Last checked 2026-08-17._ These have audio in `services/api/data/` but no row in
`library/manifest.json`, so the app cannot see them. Recorded here because a hash with no name
is otherwise indistinguishable from junk — this file is what stops them being lost twice.

`FREE` = all four stems and the paid cloud analysis are still on disk, so a row can be rebuilt
with no Replicate spend. `PAID` = restoring would mean paying Replicate again.

## Already restored (2026-08-17)

Six were identified by re-deriving their content id (normalize -> sha256), never by trusting a
filename, and put back through `library_store.upsert`. All six measured 75-97% vocal coverage,
so `role_hint` is **vocals** on evidence rather than assumption. None is `featured`, so the
curated 25-per-list dropdowns are untouched.

| name | language |
| ---- | -------- |
| Jee Karda (Badlapur) | bollywood |
| SUNIYAN SUNIYAN (Juss) | bollywood — Punjabi, filed under the bollywood list as there is no separate one |
| Maula Mere Maula (Anwar) | bollywood |
| Dil Ye Bekarar Kyun Hai (Players) | bollywood |
| CHANEL (Tyla) | english |
| Tumhi Ho Bandhu 2.0 | bollywood |

## Still out of the catalogue

### Free to restore — named on request

Audio, stems and analysis are all on disk. Nothing identifies them: no source file remains in
`song-dropbox/`, `200 songs/` or `mark-these-songs/`, and no name is stored in the analysis.
Identification clips were cut to `mark-these-songs/name-these-orphans/` for the founder to name
by ear.

| id | bpm | key | length | vocal |
| -- | --- | --- | ------ | ----- |
| `17bae5e9f6536bf861ed60e115214c053b2900734aeb6e964379be7d8d393380` | 125 | 8A | 3:37 | 76% |
| `43d69a281e6c1309694f624a5797cb3e265149238e9017ebae082f7b2d00466e` | 130 | 6B | 4:06 | 87% |
| `5406babe63c088d455b4b7765d583af5c3f474d2fb252e5bcd4dfac8e0ac27fe` | 100 | 6B | 2:58 | 0% |
| `8bfb93aa3d0c4d98de248f54f6815060bdeb75737e679f0840ac20128089ffae` | 125 | 11A | 3:27 | 69% |
| `d03d9cbd943ad12bcfc496265d389d0fa9dd3f875f8a57e4114c2943dac0da43` | 120 | 1B | 4:06 | 83% |
| `f11228cdbd1586e4b808273b14b688a2898fc4fd524c0784d8c27974e0349232` | 122 | 10B | 5:17 | 70% |

### Would cost Replicate money to restore

Founder decision 2026-08-17: **not restoring these.** Left here so the decision is on the record
and the ids are not lost. One of them is `luther.mp3`.

| id | what is missing |
| -- | --------------- |
| `5cf2ce3275b2e0c96be93af399c6686fa3f2ef592071c62301a7211710e21e9b` | stems 4/4, analysis no |
| `de37e247ae110513aa3ea7f7de805c237433dfeb74834590afc3e7cf184ad2ef` | stems 0/4, analysis no |
| `df7427e3eabb1a96b6fbfaa3fe983dd42dc83a4469b66e9930a490c976e99026` | stems 0/4, analysis no |
| `e11b5aef67e3539e91306d58af1728a48b544481b56098449bd5c0220f6ac301` | stems 4/4, analysis no |
| `e983825d8b3db67e873cc5aecf44a68a2ab6f12ae7912622fe56d4656ffdcd98` | stems 0/4, analysis no |

