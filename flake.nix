{
  description = "gnc-propsplit : saisie GnuCash avec auto-complétion proportionnelle";

  # Même révision que la configuration NixOS du poste : le GnuCash ci-dessous
  # est alors identique à celui de l'interface graphique (et déjà compilé).
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/da6dc0e7b26060f2f71ce3ef7088fb56ee44fa36";

  outputs =
    { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      # Le livre utilise des cryptomonnaies déclarées comme devises : sans ce
      # patch (le même que dans /config/Nix/common/overlay.nix), le moteur les
      # rejette au chargement et détache les comptes concernés de leur
      # commodité. Le CLI doit charger le livre exactement comme l'interface.
      gnucash = pkgs.gnucash.overrideAttrs (attrs: {
        patches = attrs.patches ++ [ ./nix/crypto-currencies.patch ];
        doCheck = false;
      });
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
