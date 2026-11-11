# SPEC — meraki-netops-iac

Projeto de portfólio: **gerenciar a configuração de uma rede Cisco Meraki como código**.
O estado desejado fica em arquivos YAML versionados no Git; uma CLI em Python compara
com o estado real (via Dashboard API), mostra o plano, aplica com backup automático e
permite rollback. Inspirado no fluxo plan/apply do Terraform.

Código escrito do zero, **somente com dados fictícios**. Nenhum dado, IP, nome ou
código de empresa/cliente real.

## Objetivo (o que um recrutador deve enxergar)

1. Rede como código: YAML → plano → aplicação, idempotente.
2. Segurança operacional: dry-run por padrão, backup antes de cada mudança, rollback.
3. Engenharia: testes automatizados, CI no GitHub Actions, código tipado e documentado.
4. Roda **sem conta Meraki**: modo simulado (API falsa em memória) para testes e demo.

## Escopo da v1

Recursos gerenciados em uma rede com MX (appliance):

| Recurso | Endpoint Meraki (API v1) | Operações |
|---|---|---|
| VLANs | `/networks/{id}/appliance/vlans` | criar, atualizar, remover |
| Regras de firewall L3 | `/networks/{id}/appliance/firewall/l3FirewallRules` | substituir a lista inteira (a API trata como lista única) |

Fora da v1 (possíveis próximas versões): SSIDs, switch ports, VPN site-to-site.

## Estrutura do estado desejado

```yaml
# networks/filial-exemplo.yaml
network: N_000000000000000000      # ID fictício
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
  - comment: Bloqueia visitantes -> corporativa
    policy: deny
    protocol: any
    src_cidr: 10.10.20.0/24
    dest_cidr: 10.10.10.0/24
```

Validação com Pydantic (subnet válida, appliance_ip dentro da subnet, IDs de VLAN únicos,
VLAN 1–4094).

## CLI

```
netops validate networks/            # valida os YAML (sem acessar a API)
netops plan     networks/            # mostra o diff: + criar, ~ alterar, - remover
netops apply    networks/ --yes      # aplica (sem --yes só mostra o plano)
netops backup   <network>            # salva o estado atual em backups/<network>/<timestamp>.json
netops rollback <network> <arquivo>  # restaura um backup (também mostra plano antes)
```

Regras:
- `apply` sempre faz **backup automático** antes de alterar.
- `apply` **não remove** VLANs que não estão no YAML, a não ser com `--prune`.
- Após aplicar, relê o estado e confirma que bate com o desejado (verificação pós-mudança).
- Credencial só por variável de ambiente `MERAKI_API_KEY`; nunca em arquivo.
- `--simulate` usa a API falsa em memória (padrão nos testes e na demo do README).

## Arquitetura

```
src/netops/
  models.py      # Pydantic: estado desejado
  client.py      # interface MerakiClient + implementação real (SDK oficial `meraki`)
  fake.py        # FakeMerakiClient em memória (testes/simulação)
  planner.py     # calcula o diff desejado x atual → lista de ações
  executor.py    # aplica ações, backup, verificação pós-mudança
  backup.py      # salvar/ler backups JSON
  cli.py         # Typer
tests/           # pytest: models, planner, executor, rollback (tudo contra o fake)
.github/workflows/
  ci.yml         # lint (ruff) + tipos (mypy) + testes em PR e push
  plan.yml       # em PR que altera networks/: roda `validate` + `plan --simulate` e comenta o plano no PR
```

Stack: Python 3.12, `meraki` (SDK oficial), Pydantic v2, Typer, Rich, pytest, ruff, mypy, uv.

## Critérios de aceite

1. `pytest` passa: validação, plano (criar/alterar/remover/sem mudanças), apply idempotente
   (2º apply = sem mudanças), backup gerado antes do apply, rollback restaura o estado.
2. `netops plan --simulate` e `apply --simulate --yes` rodam do zero seguindo o README.
3. CI verde no GitHub Actions; workflow de plano comenta o diff no PR.
4. Varredura de segredos limpa (nenhuma chave/IP real no repo).

## Limitações declaradas

- Não testado contra uma organização Meraki real nesta versão (a API real é implementada
  pelo SDK oficial, mas a validação é feita contra o simulador). O README diz isso.
