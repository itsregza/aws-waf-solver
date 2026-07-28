# aws waf solver

node zoey vm + gemini grid for miniso-style aws waf tokens.

## needs

- python 3.10+
- node on PATH
- gemini key

## setup

```
pip install -r requirements.txt
```

fill in `gemini_api_key`. optional `proxy` as `host:port:user:pass`.

## run

```
py solve.py
```

## layout

```
solve.py          cli
solver/waf.py     token flow
solver/zoey.py    node vm
solver/vlm.py     gemini grid
js/zoey_vm.js
js/challenge.js
```

same proxy for solve and whatever requests you send after. token ~60s.
