# Vivint Camera Plugin for Scrypted

Fork of [scryptedapp/blink](https://github.com/scryptedapp/blink) (a Python-runtime Scrypted
camera plugin) with the Blink API swapped for [vivintpy](https://github.com/natekspencer/vivintpy).

## Build / deploy 

```bash
npm install
npm run build
# then deploy via VS Code (scrypted-vscode-launch) or scrypted-deploy
```

The Scrypted Python runtime installs `src/requirements.txt` (`vivintpy`) on plugin load.
