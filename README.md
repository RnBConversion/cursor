# asistentas

Asmeninis AI asistentas, veikiantis tavo terminale. Claude Opus 5 protas,
paieška internete, tavo paties parašytas charakteris, pokalbiai lieka tavo
kompiuteryje.

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
| `/modelis`, `/pastangos` | pakeisti modelį ar mąstymo gylį |
| `/paieska on\|off` | paieška internete |
| `/mastymas on\|off` | rodyti, ką modelis galvoja |
| `/asmenybe` | kur redaguoti charakterį |

`Ctrl+C` nutraukia atsakymą (asistentas lieka veikti), `Ctrl+D` išeina.
Rodyklės aukštyn/žemyn — ankstesni klausimai.

## Kaip pasidaryti savu

Viskas gyvena `~/.asistentas/`:

```
~/.asistentas/
├── asmenybe.md      ← charakteris: tonas, kalba, ko niekada nedaryti
├── config.toml      ← modelis, pastangos, paieška, vieta
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
```

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
agent.py     užklausos Claude API: srautas, paieška, tęsimas, atsisakymai
render.py    markdown → terminalas, nelaukiant atsakymo pabaigos
session.py   pokalbiai JSON failuose
config.py    nustatymai ir asmenybė
pricing.py   žetonai ir kaina
lt.py        lietuviška daugiskaita
```

Keli sprendimai, kurie nėra akivaizdūs:

- **Paieška vyksta Anthropic serveriuose** (`web_search` įrankis), todėl
  nereikia nei paieškos API rakto, nei HTML skaitymo. Modelis pats nusprendžia,
  kada ieškoti; tu matai, ko jis ieškojo.
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

Pokalbiai guli tik tavo kompiuteryje (`~/.asistentas/sesijos/`, teisės 600).
Klausimai keliauja į Anthropic API — tiek, kiek reikia atsakymui. Paieškos
užklausas mato ir paieškos tiekėjas. Jei nori visiškai neišeiti iš kompiuterio,
reikėtų vietinio modelio (Ollama) — tai jau kitas projektas.

## Testai

```bash
pip install pytest && pytest -q      # 109 testų, tinklo neliečia
```

Testai naudoja suklastotą API klientą, todėl nieko nekainuoja ir veikia be rakto.
