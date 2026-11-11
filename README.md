# aws waf solver

gets an `aws-waf-token` for sites behind aws waf. runs the real `challenge.js` in a node vm for the zoey fingerprint, and solves the image captcha with gemini or openai when the site serves one.

## needs

- python 3.10+
- node 18+ on PATH
- gemini or openai key (only used if the site shows a captcha)

## setup

```
pip install -r requirements.txt
cp config.example.json config.json
```

put your key in `config.json`, or set `GEMINI_API_KEY` / `OPENAI_API_KEY`.

## run

```
python solve.py https://minisoshop.co.uk/
python solve.py https://minisoshop.co.uk/ -p host:port:user:pass
python solve.py --provider openai -q
```

the token goes to stdout, step timings go to stderr. `-q` prints the token only.

## use it in code

```python
from solver.vlm import configure
from solver.waf import solve

configure(api_key="...")
token = solve("https://minisoshop.co.uk/", proxy="host:port:user:pass")
```

already have the challenge page html? pass `html=` and it skips the page fetch.

## layout

```
solve.py          cli
solver/waf.py     token + captcha flow
solver/zoey.py    node vm daemon
solver/vlm.py     image captcha (gemini / openai)
js/zoey_vm.js     sandbox that runs challenge.js
js/challenge.js   fallback copy if the live one can't be fetched
```

use the same proxy for the solve and whatever requests you send after. token ~60s.
