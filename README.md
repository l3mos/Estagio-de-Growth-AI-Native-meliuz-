# Analisador de Testes A/B de Cashback — Méliuz (teste técnico Growth AI-Native)

## TESTE TÉCNICO

O enunciado pedia uma solução reutilizável que recebe o CSV de um teste A/B
de cashback e devolve uma recomendação: qual variante escalar pra 100% do
tráfego. Fiz o script genérico de a fim de que o time vai reusar todo mês, pra qualquer teste novo.
Os relatórios individuais gerados pelo script estão em
`reports/`.

## Como rodar

```bash
pip install -r requirements.txt

python analyze_ab_test.py \
  --file data/dataset_01_parceiroA.csv \
  --test-name "Cashback Parceiro A" \
  --test-description "Teste de 3 níveis de cashback no Parceiro A."
```

O mesmo comando, só trocando o `--file`, roda pros outros dois datasets sem
eu mexer em nenhuma linha de código:

```bash
python analyze_ab_test.py --file data/dataset_02_parceiroB.csv --test-name "Cashback Parceiro B" --test-description "..."
python analyze_ab_test.py --file data/dataset_03_parceiroC.csv --test-name "Cashback Parceiro C" --test-description "..."
```

Cada execução gera:
- `reports/<nome-do-teste>.md` — relatório completo, com recomendação no topo
- `reports/<nome-do-teste>_chart.png` — gráfico comparando margem e volume
- uma linha nova em `registry/tracking_sheet.csv` — a planilha de acompanhamento

### Rodando via um agente de IA

Se você abrir esse repositório no Claude Code, Cursor, ou qualquer agente
parecido, dá pra simplesmente pedir em português mesmo, tipo:

> "Analisa o teste A/B em `data/dataset_02_parceiroB.csv`, chama de
> 'Cashback Parceiro B' e descreve como teste de 3 níveis de cashback
> rodado em maio/junho de 2011."

O agente lê o `AGENTS.md` (que descreve exatamente como e quando chamar o
script) e faz isso sozinho, sem precisar reescrever nenhuma lógica de
análise no meio da conversa.

## Como organizei o código

```
analyze_ab_test.py          # CLI -- é por aqui que tudo começa
ab_analyzer/
  loader.py                  # lê o CSV e limpa dado ruim (formato de moeda, duplicata, etc)
  metrics.py                 # calcula métrica por grupo + roda os testes estatísticos
  decision.py                 # decide qual variante recomendar (regra explicada no arquivo)
  report.py                    # monta o relatório em Markdown + o gráfico
  registry.py                   # escreve a linha na planilha de acompanhamento
AGENTS.md                   # como um agente de IA deve chamar o script
ANALISE_CRITICA.md          # minha leitura crítica dos 3 datasets, antes de qualquer automação
data/                       # os 3 datasets fornecidos no teste
reports/                    # relatórios já gerados (um .md + um .png por teste)
registry/tracking_sheet.csv # planilha consolidada de todos os testes rodados
```

Separei cada etapa (ler, calcular, decidir, relatar, registrar) num módulo
próprio porque isso deixa fácil reaproveitar qualquer pedaço isolado depois
-- por exemplo, se um dia o time quiser plugar isso num bot de Slack ou
numa API interna, só precisa importar `ab_analyzer`, sem depender do CLI.

## A regra de decisão, resumida

A métrica que decide é **margem** (comissão do parceiro − cashback pago),
porque é o lucro de verdade que o Méliuz fica com o teste -- não só volume
(compradores/GMV), que sobe quase sempre que o cashback fica mais generoso,
sem necessariamente compensar financeiramente. Isso não é só teoria: é
exatamente o que apareceu nos 3 datasets (detalhes em `ANALISE_CRITICA.md`).

- Se o baseline já é a variante com maior margem, ele fica -- não preciso
  de teste estatístico pra justificar não mudar nada.
- Se outra variante tem margem maior, só recomendo trocar se essa vantagem
  for estatisticamente significativa (Welch's t-test **e** Mann-Whitney,
  p < 0,05) contra o baseline. Se não for, marco como inconclusivo e
  recomendo manter o baseline rodando por mais tempo.
- Se a variante recomendada perde em volume (compradores/GMV) pra outra,
  isso aparece no relatório como trade-off explícito -- não escondo esse
  tipo de informação atrás da recomendação principal.

A lógica completa (com a explicação de por que decidi assim) está comentada
em `ab_analyzer/decision.py`.

## Como a solução lida com dado ruim

Considerando que um que um dataset futuro pode não vir tão limpo quanto os 3 que recebi (que não tinham nenhum problema, na real). O `loader.py` trata, sem quebrar
a execução:

- valor monetário em formatos diferentes (`R$ 1.234`, `R$ 1.234,56`, vazio)
- nome de coluna com acento/capitalização diferente
- nome de grupo com espaço sobrando ou capitalização inconsistente
- linha duplicada
- campo vazio ou valor negativo (não existe -5 compradores)
- data em formato diferente
- dia sem observação no meio do período do teste
- grupos com número de dias bem diferente entre si (alerta de possível
  problema na divisão de tráfego)

Tudo isso fica registrado na seção "Qualidade dos dados" de cada relatório
-- Destacando a robustez do código em cada um dos relatórios

## Planilha de acompanhamento (Google Sheets)

**Link da planilha do Google Sheets:**
`[https://docs.google.com/spreadsheets/d/1zbyb6wo8A_x-2ESdf7S3cyeWIgSWepK2x4Ht00AynzQ/edit?usp=sharing]`
