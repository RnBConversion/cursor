# asistentas

Asmeninis AI asistentas, veikiantis tavo terminale. Claude Opus 5 protas,
paieška internete, ilgalaikė atmintis, prieiga prie tavo failų, klausimai balsu
ir tavo paties parašytas charakteris. Pokalbiai ir atmintis lieka tavo
kompiuteryje — o prireikus ir visas galvojimas: antras variklis yra Ollama,
sukanti modelius vietoje, be interneto ir be mokesčių.

```
tu ▸ kiek dabar kainuoja elektra?

🔎 ieškau: elektros kaina Lietuvoje
Trumpai

Elektros kaina krito iki 0.12 €/kWh.
  • naktinis tarifas pigesnis
  • savaitgalį dar mažiau
  1. LRT naujienos — https://lrt.lt/x
  $0.02 · 2 316 žet. · 1 paieška · talpykla
```

## Paleidimas

Reikia Python 3.11+ ir Anthropic API rakto.

> **macOS:** sistemos `python3` dažnai yra 3.9 — su juo neveiks (`tomllib`
> atsirado 3.11). Pasitikrink `python3 --version`; jei mažiau nei 3.11:
> `brew install python`. Homebrew Python turi ir tikrą GNU readline, todėl
> gražiau veikia istorija ir balsu atpažinto teksto taisymas.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...      # raktas: console.anthropic.com/settings/keys
asistentas
```

Raktą verta įsidėti į `~/.bashrc` arba `~/.zshrc`, kad nereikėtų kartoti.

## Kaip naudoti

```bash
asistentas                              # pokalbis
asistentas "kada kitas traukinys į Kauną"   # vienas klausimas ir atgal į terminalą
cat laiskas.txt | asistentas "atsakyk mandagiai"
asistentas "santrauka" > santrauka.md   # nukreipus gaunasi švarus markdown
asistentas --tesk "o kas toliau?"       # tęsti vakarykštį pokalbį
```

Pokalbyje:

| komanda | ką daro |
| --- | --- |
| `/nauja` | pradėti naują pokalbį |
| `/sesijos`, `/tesk [id]` | ankstesni pokalbiai |
| `/istorija` | šio pokalbio eiga |
| `/kaina` | kiek iki šiol kainavo |
| `/tiekejas anthropic\|ollama` | kas galvoja: Claude ar tavo Mac'as |
| `/modelis`, `/pastangos` | pakeisti modelį ar mąstymo gylį |
| `/paieska on\|off` | paieška internete |
| `/mastymas on\|off` | rodyti, ką modelis galvoja |
| `/balsas` | užduoti klausimą balsu |
| `/atmintis` | ką jis apie tave įsiminė (`viskas` — turinys, `pamirsk` — ištrinti) |
| `/failai` | kuriuos katalogus jis mato |
| `/asmenybe` | kur redaguoti charakterį |

`Ctrl+C` nutraukia atsakymą (asistentas lieka veikti), `Ctrl+D` išeina.
Rodyklės aukštyn/žemyn — ankstesni klausimai.

## Kaip pasidaryti savu

Viskas gyvena `~/.asistentas/`:

```
~/.asistentas/
├── asmenybe.md      ← charakteris: tonas, kalba, ko niekada nedaryti
├── config.toml      ← modelis, pastangos, paieška, vieta, failai, MCP
├── atmintis/        ← ką jis apie tave žino (paprasti tekstiniai failai)
├── istorija         ← klausimų istorija (rodyklės aukštyn)
└── sesijos/         ← pokalbiai JSON formatu
```

**`asmenybe.md`** yra svarbiausias failas — tai sistemos promptas. Rašyk jame
taip, kaip aiškintum naujam žmogui: „atsakyk trumpai", „aš dirbu su Python",
„jei klausiu apie teisę, visada paminėk, kad nesi teisininkas". Keitimai
galioja nuo kito paleidimo.

**`config.toml`** — modelis, mąstymo gylis, paieškos ribojimai, vieta:

```toml
modelis = "claude-opus-5"     # arba pigesnis "claude-sonnet-5"
pastangos = "high"            # low | medium | high | xhigh | max
paieska = true
paieskos_limitas = 5
salis = "LT"
laiko_juosta = "Europe/Vilnius"
# leidziami_domenai = ["lrt.lt", "delfi.lt"]   # ieškoti tik čia

atmintis = true
# failu_katalogai = ["~/Dokumentai", "~/uzrasai"]
```

## Atmintis

Įjungta iš karto. Asistentas pats nusprendžia, ką verta įsiminti — vardą,
kalbą, įrankius, pasikartojančius darbus — ir kitą kartą to nebeklausia:

```
tu ▸ nuo šiol atsakinėk trumpiau, be įžangų

🧠 įsimenu
Gerai.
```

Atmintis — tai paprasti tekstiniai failai `~/.asistentas/atmintis/`. Gali juos
atsiversti, pataisyti ranka arba ištrinti: `/atmintis` parodo, kas ten yra,
`/atmintis viskas` — visą turinį, `/atmintis pamirsk` — išvalo viską.
Slaptažodžių, kodų ir banko duomenų įsiminti jam liepta niekada.

Išjungti: `atmintis = false`.

## Tavo failai

Kol `failu_katalogai` tuščias, asistentas tavo failų **nemato iš viso** — tų
įrankių jam net nesiunčiame. Nurodžius katalogus, jis gali juose ieškoti ir
skaityti:

```
tu ▸ kada mano projekto terminas?

📂 ieškau failuose: terminas
📄 skaitau: darbas/planas.md
Projekto X terminas — spalio 1 d.
```

Tik skaitymas: failų jis nekeičia ir netrina. Keliai tikrinami pagal tavo
sąrašą — už jo ribų neišeina net simbolinė nuoroda, `..` ar absoliutus kelias.
Paslėpti katalogai (`.git`, `.ssh` ir pan.) praleidžiami, dvejetainiai failai
neskaitomi.

## Balso įvestis

```
tu ▸ /balsas
🎤 kalbėk… (Enter — baigti, Ctrl+C — atšaukti)
⏳ atpažįstu…
tu ▸ kada mano projekto terminas_
```

Atpažintas tekstas atsiranda **įvesties eilutėje**, o ne iškart keliauja į
API: neteisingai išgirstą žodį pataisai ir tik tada spaudi Enter. `--balsas`
paleidžia asistentą taip, kad kiekvienas klausimas prasidėtų įrašymu.

Reikia dviejų dalykų — nė vienas nėra šio projekto priklausomybė:

```bash
brew install sox              # macOS  (Linux: sudo apt install sox)
pip install faster-whisper    # atpažinimo variklis; modelis parsisiunčia pats
```

> **macOS, pirmas kartas:** sistema paklaus, ar leisti terminalui naudoti
> mikrofoną. Jei prašymo nepastebėsi arba atmesi, įrašas bus tyla, o asistentas
> pasakys „negirdėjau nieko" — leidimą įjungsi per System Settings → Privacy &
> Security → Microphone → Terminal (arba iTerm).
>
> **Apple Silicon:** `whisper.cpp` naudoja GPU per Metal ir yra pastebimai
> greitesnis už faster-whisper, kuris čia suka tik procesorių:
> `brew install whisper-cpp`, parsisiųsk `ggml-large-v3.bin` ir nurodyk jį
> `whisper_modelis` eilutėje. Mainai: modelį reikia parsisiųsti pačiam,
> faster-whisper tai padaro už tave.

Tiek. `/balsas` pats susiras, kas įdiegta, o ko trūksta — pasakys tiksliai,
kurios komandos trūksta. Vietoj `sox` tinka `arecord`, `pw-record` ar `ffmpeg`;
vietoj `faster-whisper` — `whisper.cpp` arba visai sava komanda:

```toml
[balsas]
kalba = "lt"                 # arba "auto", jei maišai kalbas
# modelis = "large-v3"       # lietuvių kalbai verta didelio: "small" klysta dažnai
# variklis = "whisper.cpp"
# whisper_modelis = "~/modeliai/ggml-large-v3.bin"
# komanda = "mano-stt --lang {kalba} {failas}"
# maks_sekundes = 120
```

Garsas niekur neišeina: įrašas guli laikiname faile, atpažįstamas tavo
kompiuteryje ir iš karto ištrinamas. Į Anthropic API keliauja tik tekstas —
tas pats, kurį matai eilutėje.

Lietuvių kalbai realiai reikia `large-v3` (arba `large-v3-turbo`) — mažesni
modeliai supranta angliškai, bet lietuviškai klysta tiek, kad taisyti ilgiau
nei parašyti. Pirmas paleidimas užtrunka: modelis parsisiunčiamas.

## Gmail, kalendorius ir kita (MCP)

Vietoj atskiro kodo kiekvienai paslaugai asistentas jungiasi prie **MCP
serverių** — tai standartas, kuriuo Gmail, kalendorius, Slack ar Notion
pasiūlo savo įrankius. Nurodai serverį, ir jo įrankiai atsiranda pokalbyje:

```toml
[[mcp]]
pavadinimas = "gmail"
url = "https://mcp.pavyzdys.lt/gmail"
token_env = "GMAIL_MCP_TOKEN"     # raktas – aplinkos kintamajame, ne čia
```

```bash
export GMAIL_MCP_TOKEN=...
```

Prisijungimą atlieka Anthropic serveriai, tad tau nereikia nei OAuth kodo, nei
bibliotekų. Adresas privalo būti `https://`; raktas į `config.toml` nerašomas
niekada. Veikiančio MCP serverio reikės susirasti arba pasileisti pačiam —
šis projektas prie jo tik prisijungia.

## Be interneto: Ollama tavo Mac'e

Asistentas moka galvoti dviem varikliais. Antrasis — [Ollama](https://ollama.com):
modeliai, sukantys tavo kompiuteryje. Jokio rakto, jokių mokesčių, nė vienas
žodis neišeina iš Mac'o.

```bash
brew install ollama
ollama pull qwen3:32b
```

```
tu ▸ /tiekejas ollama
tiekėjas: ollama qwen3:32b (lokaliai)
paieškos internete ir MCP šiuo varikliu nėra

tu ▸ kaip gaminti cepelinus?
Bulvės, mėsa, grietinė. Virti 25 min.
  lokaliai · 664 žet.
```

Perjungiama pokalbio viduryje — istorija lieka ta pati, tad vieną klausimą gali
atsakyti lokalus modelis, o kitą, sunkesnį, Claude. Nuolatinį pasirinkimą
nurodai `tiekejas` eilute `config.toml`.

Veikia ir Ollama debesis (mokama prenumerata): `adresas = "https://ollama.com"`
ir `export OLLAMA_API_KEY=...`. Tada modeliai dideli, bet duomenys vėl išeina
iš kompiuterio — prasmė lieka tik kainos, ne privatumo.

| | Claude | Ollama |
| --- | --- | --- |
| atmintis, failai | ✓ | ✓ |
| balso įvestis | ✓ | ✓ |
| paieška internete | ✓ | — |
| Gmail, kalendorius (MCP) | ✓ | — |
| prompto talpykla | ✓ | — |
| kaina | pagal žetonus | nemokama (lokaliai) |

Kai paieškos nėra, modeliui tai pasakoma sistemos prompte — kad į „kas naujo"
atsakytų „negaliu patikrinti", o ne prasimanytų.

**Ko realiai tikėtis.** Modelio dydį riboja RAM: 16 GB užtenka 7–14B modeliams,
32 GB — 27–32B, 64 GB — 70B. Lietuviškai atviri modeliai rašo pastebimai
prasčiau nei Opus 5, o mažesni dažnai pamiršta pasinaudoti atmintimi ar failų
paieška — o būtent tuo šis asistentas ir gyvas. Todėl numatytasis variklis
lieka Claude, o Ollama yra pasirinkimas tada, kai svarbiau privatumas arba
kai interneto tiesiog nėra.

## Kiek tai kainuoja

Mokama už sunaudotus žetonus, ne už prenumeratą. Kainos už 1 mln. žetonų:

| modelis | įvestis | išvestis |
| --- | --- | --- |
| `claude-opus-5` | $5 | $25 |
| `claude-sonnet-5` | $2 | $10 |
| `claude-haiku-4-5` | $1 | $5 |

Paieška internete — $10 už 1000 paieškų. Tipinis klausimas su viena paieška
kainuoja apie 1–3 centus, todėl kaina rodoma po kiekvieno atsakymo.

Pigiau išeina trimis būdais: `pastangos = "medium"` (pokalbiams skirtumo
dažnai nematyti), pigesnis modelis kasdienėms smulkmenoms ir ilgesni pokalbiai
vietoj naujų — pokalbio pradžia keliauja į talpyklą ir kainuoja 10 kartų
mažiau (footeryje tada matai žodį „talpykla").

## Kaip veikia

```
cli.py       pokalbio ciklas, komandos, klaidos žmogiškai
agent.py     užklausos Claude API: srautas, įrankių ciklas, tęsimas
ollama.py    antras variklis: modeliai tavo kompiuteryje arba Ollama debesyje
render.py    markdown → terminalas, nelaukiant atsakymo pabaigos
voice.py     balso įvestis: įrašymas ir atpažinimas tavo kompiuteryje
memory.py    ilgalaikė atmintis (Anthropic atminties įrankis)
files.py     tavo failų paieška ir skaitymas, griežtai ribotuose kataloguose
session.py   pokalbiai JSON failuose
config.py    nustatymai, asmenybė, MCP serveriai
pricing.py   žetonai ir kaina
lt.py        lietuviška daugiskaita
```

Keli sprendimai, kurie nėra akivaizdūs:

- **Istorija visada saugoma Anthropic blokais**, net kai atsako Ollama:
  `ollama.py` verčia į OpenAI formatą tik prieš siunčiant ir atgal. Todėl tą
  patį pokalbį gali tęsti kitu varikliu, o sesijų failai lieka vienodi.
- **Paieška ir MCP vyksta Anthropic serveriuose**, o atmintis ir failai — tavo
  kompiuteryje. Todėl vienam klausimui gali prireikti kelių apsikeitimų su API:
  modelis paprašo įrankio, mes jį įvykdome ir grąžiname rezultatą. Ciklas
  ribotas 16 žingsnių, kad klaida nesuktų rato ir nekainuotų.
- **Visi vieno žingsnio įrankių rezultatai grąžinami viena žinute** — kitaip
  modelis palaipsniui nustoja kviesti įrankius lygiagrečiai.
- **Nutraukus (Ctrl+C) įrankių ciklą** pakibęs iškvietimas uždaromas klaidos
  rezultatu: API reikalauja, kad po kiekvieno `tool_use` eitų `tool_result`,
  antraip kita užklausa nulūžtų.
- **Prieš sakant „kalbėk" palaukiama, kol mikrofonas realiai atsidarys** —
  `sox` ir `ffmpeg` pasileidžia ne akimirksniu, o pirmas žodis dingsta tyliai.
  Jei įrašymas nulūžta (mikrofonas užimtas), sužinai tuoj pat, o ne
  prakalbėjęs minutę.
- **Šiandienos data** siunčiama atskira `system` žinute, o ne sistemos prompte:
  taip promptas nesikeičia ir lieka talpykloje. Modeliams, kurie tokių žinučių
  nepriima, data keliauja į promptą.
- **Ilga paieška gali sustoti** ties serverio ciklo riba (`pause_turn`) —
  užklausa tada kartojama automatiškai, o atsakymas istorijoje lieka vientisas.
- **Nutrauktas atsakymas** (Ctrl+C) išsaugomas tiek, kiek spėta; jei nespėta
  nieko — klausimas iš istorijos pašalinamas, kad ji liktų taisyklinga.
- **Nukreipus išvestį** į failą spalvos ir tarnybinės eilutės dingsta, lieka
  švarus markdown.

## Privatumas

Pokalbiai ir atmintis guli tik tavo kompiuteryje (`~/.asistentas/`, teisės 600).
Bet viskas, ką modelis mato, keliauja į Anthropic API: klausimai, atminties
turinys ir tie failų fragmentai, kuriuos jis perskaito. Paieškos užklausas mato
ir paieškos tiekėjas.

Praktiškai tai reiškia: į `failu_katalogai` dėk tik tai, ką nebijotum parodyti.
Ne visą `~`. Atmintį bet kada peržiūrėsi ir ištrinsi (`/atmintis`), o jei nori,
kad niekas iš viso neišeitų iš kompiuterio, reikėtų vietinio modelio (Ollama) —
tai jau kitas projektas.

## Testai

```bash
pip install pytest && pytest -q      # 217 testų, tinklo neliečia
```

Testai naudoja suklastotą API klientą, todėl nieko nekainuoja ir veikia be rakto.
Atskirai tikrinama, kad nei atminties, nei failų įrankis neišeitų už jam skirtų
katalogų — kelius siūlo modelis, tad tai ne smulkmena. Balso grandinė
tikrinama su netikrais `rec` ir `stt` binarais: taip patikrinamas ir procesų
sustabdymas, ir įrašo ištrynimas, ir elgesys, kai mikrofono nėra. Ollama
tikrinama per tikrą vietinį HTTP serverį — su srautu, įrankių kvietimu ir
klaidomis, o ne per apsimestinį klientą.
