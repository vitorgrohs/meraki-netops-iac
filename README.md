# meraki-netops-iac

[![CI](https://github.com/vitorgrohs/meraki-netops-iac/actions/workflows/ci.yml/badge.svg)](https://github.com/vitorgrohs/meraki-netops-iac/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

**Configuração de redes Cisco Meraki como código.** O estado desejado fica em YAML, versionado no Git; a
ferramenta compara com a rede real, mostra o plano e aplica — com backup automático, verificação depois
da mudança e rollback. Mesmo fluxo *plan/apply* do Terraform, focado em operação de rede.

> *Cisco Meraki network configuration as code: YAML desired state → plan → apply, with automatic
> backup, post-change verification and rollback. Runs fully offline with a built-in simulator.*

## Por que

Mudança de rede feita na mão no Dashboard não tem revisão, histórico nem desfazer. Aqui:

- **Toda mudança passa por Pull Request** — o pipeline comenta no PR exatamente o que vai mudar.
- **Nada é aplicado sem ver o plano** — `apply` sem `--yes` é só simulação.
- **Backup antes de cada mudança** e **rollback com um comando**.
- **Verificação pós-mudança**: depois de aplicar, relê a rede e confirma que bate com o YAML.
- **Nada é apagado por acidente**: VLANs fora do YAML só são removidas com `--prune`.

## Exemplo

O estado desejado de uma filial ([`networks/filial-exemplo.yaml`](networks/filial-exemplo.yaml), dados fictícios):

```yaml
network: N_000000000000000001
vlans:
  - id: 10
    name: Corporativa
    subnet: 10.10.10.0/24
    appliance_ip: 10.10.10.1
  - id: 20
    name: Visitantes
    subnet: 10.10.20.0/24
    appliance_ip: 10.10.20.1
firewall_l3:
  - comment: Visitantes nao acessam a rede corporativa
    policy: deny
    src_cidr: 10.10.20.0/24
    dest_cidr: 10.10.10.0/24
  - comment: Corporativa gerencia IoT via HTTPS
    policy: allow
    protocol: tcp
    src_cidr: 10.10.10.0/24
    dest_cidr: 10.10.30.0/24
    dest_port: "443"
```

```console
$ netops plan networks/ --simulate
N_000000000000000001: 4 change(s)
+ vlan 10  Corporativa  10.10.10.0/24
+ vlan 20  Visitantes  10.10.20.0/24
+ vlan 30  IoT  10.10.30.0/24
~ firewall_l3: 0 -> 3 rules
+     deny  any  10.10.20.0/24 -> 10.10.10.0/24  # Visitantes nao acessam a rede corporativa
+     deny  any  10.10.30.0/24 -> 10.10.10.0/24  # IoT nao acessa a rede corporativa
+     allow tcp  10.10.10.0/24 -> 10.10.30.0/24:443  # Corporativa gerencia IoT via HTTPS

$ netops apply networks/ --simulate --yes
...
applied 4 change(s) - backup: backups/N_000000000000000001/20261111T002512Z.json

$ netops plan networks/ --simulate
N_000000000000000001: no changes
```

## Rodando (sem conta Meraki)

Requer [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/vitorgrohs/meraki-netops-iac && cd meraki-netops-iac
uv sync
uv run netops validate networks/
uv run netops plan  networks/ --simulate
uv run netops apply networks/ --simulate --yes
```

`--simulate` usa uma API falsa em memória (estado salvo em `.netops-sim.json`), que imita o
comportamento relevante do Dashboard: VLAN 1 padrão, regra de firewall implícita no fim da lista e
erros ao alterar VLANs inexistentes.

## Contra uma rede real

```bash
export MERAKI_API_KEY=...          # nunca em arquivo
uv run netops plan  networks/
uv run netops apply networks/ --yes
```

| Comando | O que faz |
|---|---|
| `netops validate <dir>` | Valida os YAML (sem acessar a API) |
| `netops plan <dir> [--prune]` | Mostra o diff: `+` criar, `~` alterar, `-` remover. Somente leitura |
| `netops apply <dir> [--prune] --yes` | Backup → aplica → verifica |
| `netops backup <network>` | Salva o estado atual em `backups/<network>/` |
| `netops rollback <network> <arquivo> --yes` | Restaura um backup (mostra o plano antes) |

Validações feitas antes de qualquer chamada à API: ID de VLAN 1–4094 e único, `appliance_ip` dentro da
subnet, subnets sem sobreposição, CIDRs e portas válidos, portas só com TCP/UDP, mesma rede em um só
arquivo.

## GitOps

Dois workflows em [`.github/workflows`](.github/workflows):

- **`ci.yml`** — em todo push/PR: `ruff`, `mypy --strict` e `pytest`.
- **`plan.yml`** — em PR que altera `networks/`: valida e **comenta o plano no PR**. Usa a API real se o
  secret `MERAKI_API_KEY` existir; senão, o simulador.

A aplicação continua manual (`apply --yes`) de propósito: em rede de produção, quem aplica revisa o plano
e escolhe a janela de mudança.

## Arquitetura

```
src/netops/
  models.py    # estado desejado (Pydantic) e carga dos YAML
  client.py    # interface MerakiClient + implementação com o SDK oficial `meraki`
  fake.py      # API simulada em memória (testes e --simulate)
  planner.py   # diff desejado x atual → ações ordenadas (criar, alterar, firewall, remover)
  executor.py  # backup → executa → verifica
  backup.py    # snapshots JSON e conversão de volta para estado desejado (rollback)
  cli.py       # Typer + Rich
```

O planner nunca escreve: os testes garantem que `plan` só faz chamadas de leitura. O rollback reutiliza o
mesmo caminho do `apply` (o backup vira um estado desejado com `--prune`), então também tem backup e
verificação.

## Escopo e limitações

- v0.1 gerencia **VLANs do MX** e **regras de firewall L3**. Próximos candidatos: SSIDs, portas de
  switch, VPN site-to-site.
- O backup cobre só os campos gerenciados (nome, subnet e IP da VLAN; regras L3) — não DHCP, reservas etc.
- Validado contra o simulador e a suíte de testes; a chamada real usa o SDK oficial da Cisco, mas não foi
  exercitada contra uma organização de produção nesta versão.

## Licença

MIT. Projeto pessoal de portfólio — todos os IDs, nomes e endereços são fictícios.
