# sbox-wine-docker
`sbox-wine-docker` provides a single script to run while inside of the `sbox-public` repo, which will build sbox for you. It uses docker under the hood, but you shouldn't need to worry too much about it.

## Installation
```
sudo curl -L https://raw.githubusercontent.com/vinceTheProgrammer/sbox-wine-docker/refs/heads/main/sbox-build -o /usr/local/bin/sbox-build
sudo chmod +x /usr/local/bin/sbox-build
```

## Usage
While in any `sbox-public` repo:
```
sbox-build
```
I highly recommend using `--enable-hash-cache` to enable the hash cache for smarter change based building that does not rely on `git commit`ing between every rebuild.

Consider the experimental `--enable-codegen-patch` flag to enable the application of a CodeGen.Targets patch during builds to (allegedly) skip codegen when not necessary to re-run.

Note: if Docker is not installed, started, or set up, `sbox-build` will walk you through it.

## Update
```
sudo curl -L https://raw.githubusercontent.com/vinceTheProgrammer/sbox-wine-docker/refs/heads/main/sbox-build -o /usr/local/bin/sbox-build
sudo chmod +x /usr/local/bin/sbox-build
sbox-build --pull # or sbox-build --rebuild --update
```

## Known issues
- `--test` hangs
- `--format` completely breaks

## Credit
- Used the Dockerfile created by tsktp as the foundation: https://github.com/tsktp/sbox-public-linux-docker
- DrakeFruit's fork of tsktp's repo was the inpiration for the build script https://github.com/DrakeFruit/sbox-public-linux-docker
- ChatGPT and Grok wrote much of the Dockerfile additions and build scripts, but I understand it 95% line for line, so blame ~~any~~95% of problems on me

## License
License is MIT, so do whatever with it
