{
  description = "gnc-propsplit : saisie GnuCash avec auto-complétion proportionnelle";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      inherit (pkgs) gnucash;
      # Les bindings sont compilés pour le Python de nixpkgs : il faut le même.
      python = pkgs.python3;
      gnucashSitePackages = "${gnucash}/${python.sitePackages}";
      runtimeDeps = ps: [
        ps.prompt-toolkit
        ps.tomli-w
      ];
    in
    {
      packages.${system}.default = python.pkgs.buildPythonApplication {
        pname = "gnc-propsplit";
        version = "0.1.0";
        pyproject = true;
        src = ./.;
        build-system = [ python.pkgs.setuptools ];
        dependencies = runtimeDeps python.pkgs;
        makeWrapperArgs = [ "--prefix PYTHONPATH : ${gnucashSitePackages}" ];
        nativeCheckInputs = [ python.pkgs.pytestCheckHook ];
        preCheck = "export PYTHONPATH=${gnucashSitePackages}:$PYTHONPATH HOME=$TMPDIR";
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = [
          (python.withPackages (ps: runtimeDeps ps ++ [ ps.pytest ]))
          gnucash
        ];
        shellHook = ''
          export PYTHONPATH=${gnucashSitePackages}:$PWD''${PYTHONPATH:+:$PYTHONPATH}
        '';
      };
    };
}
