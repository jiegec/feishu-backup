{ pkgs ? import <nixpkgs> {}
}:

pkgs.mkShell {
  buildInputs = with pkgs; [
    python39Full
    python39Packages.requests
    python39Packages.autopep8
  ];
}
