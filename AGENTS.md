# Instruções pra agentes de IA (Claude Code, Cursor, ChatGPT, Gemini...)

Esse arquivo segue a convenção `AGENTS.md`, que ferramentas de codificação
com IA costumam ler automaticamente.
## O que fazer quando alguém pedir uma análise

Se o pedido for algo do tipo:

> "Analisa esse teste A/B, aqui está o `dataset_novo.csv`"
> "Roda a análise do teste de cashback do parceiro X"
> "Qual variante eu devo escalar nesse teste?"

Basta chamar o `analyze_ab_test.py` que já está na raiz do repositório. Não
precisa (e não deveria) escrever nenhuma lógica de análise nova -- ela já
existe em `ab_analyzer/` e funciona pra qualquer CSV no schema esperado
(ver `README.md`).

```bash
python analyze_ab_test.py \
  --file <caminho_do_csv> \
  --test-name "<nome curto do teste>" \
  --test-description "<contexto: o que está sendo testado e por quê>"
```

Parâmetros opcionais:
- `--baseline "Grupo 1"` — define o grupo controle na mão (por padrão é o
  primeiro em ordem alfabética).
- `--reports-dir reports` — pasta de saída do relatório e do gráfico.
- `--registry-csv registry/tracking_sheet.csv` — planilha de acompanhamento.

## Se a pessoa não te der nome/descrição do teste

- Sem nome: usa o nome do arquivo.
- Sem descrição: tenta inferir do contexto da conversa (nome do parceiro,
  período, o que parece estar sendo testado). Se não der pra inferir nada
  minimamente confiável, é melhor perguntar do que inventar uma hipótese
  que o usuário não mencionou.

## Depois de rodar

1. Abre o `.md` gerado em `reports/` e resume a recomendação pro usuário em
   linguagem natural -- não jogue o markdown bruto sem contexto nenhum.
2. Avisa que a linha também foi pra `registry/tracking_sheet.csv` (e pro
   Google Sheets, se estiver configurado).
3. Se o script der erro de schema inválido, mostra a mensagem de erro e
   pergunta se o arquivo é mesmo um export de teste A/B de cashback do
   Méliuz (colunas esperadas: Data, Grupos de usuários, Parceiro,
   compradores, comissão, cashback, vendas totais).

## O que não fazer

- Não reescreve a lógica de decisão dentro da conversa -- ela já existe em
  `ab_analyzer/decision.py` e o objetivo é reusar, não duplicar.
- Não "chuta" a recomendação sem rodar o script de verdade -- os números e
  os testes de significância vêm do cálculo real.
- Não escala nenhuma variante em produção sozinho -- a saída do script é
  uma recomendação pra um humano decidir e agir.
