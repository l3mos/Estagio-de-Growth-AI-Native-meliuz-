"""
report.py

Monta o relatório final em Markdown. Tentei escrever pensando em quem vai
ler: alguém do time de Growth que não quer abrir um notebook Python, quer
ler um documento com a recomendação logo no topo e os números de apoio
depois, caso queira conferir.

Uso matplotlib só pra gerar um gráfico simples de apoio (margem e volume
por grupo) -- nada muito elaborado, só o suficiente pra visualizar o
trade-off que fica bem mais claro em imagem do que em tabela.
"""
from __future__ import annotations

import os
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .decision import Decisao
from .loader import RelatorioDeLimpeza
from .metrics import ResumoDoGrupo, TesteEntreGrupos


def _moeda(v: float) -> str:
    if pd.isna(v):
        return "N/A"
    return f"R$ {v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _percentual(v: float) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{v * 100:.2f}%"


def gerar_grafico(resumos: dict[str, ResumoDoGrupo], caminho_saida: str, titulo: str):
    grupos = list(resumos.keys())
    margem = [resumos[g].margem_media_dia for g in grupos]
    compradores = [resumos[g].compradores_media_dia for g in grupos]

    fig, eixos = plt.subplots(1, 2, figsize=(10, 4))
    eixos[0].bar(grupos, margem, color="#2E7D32")
    eixos[0].set_title(f"Margem média/dia (R$)\n{titulo}")
    eixos[0].tick_params(axis="x", rotation=20)

    eixos[1].bar(grupos, compradores, color="#1565C0")
    eixos[1].set_title(f"Compradores médios/dia\n{titulo}")
    eixos[1].tick_params(axis="x", rotation=20)

    plt.tight_layout()
    fig.savefig(caminho_saida, dpi=130)
    plt.close(fig)


def _tabela_testes(testes: list[TesteEntreGrupos]) -> str:
    if not testes:
        return "_Não deu pra comparar (dados insuficientes)._\n"
    linhas = [
        "| Comparação | Média baseline | Média variante | Diferença | Diferença % | p (Welch) | p (Mann-Whitney) | Significativo (95%)? | IC 95% da diferença |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t in testes:
        linhas.append(
            f"| {t.grupo_a} vs {t.grupo_b} | {t.media_a:,.2f} | {t.media_b:,.2f} | "
            f"{t.diferenca:,.2f} | {t.diferenca_pct:,.1f}% | {t.p_valor_welch:.4f} | "
            f"{t.p_valor_mannwhitney:.4f} | {'Sim' if t.significativo else 'Não'} | "
            f"[{t.ic95_baixo:,.2f}; {t.ic95_alto:,.2f}] |"
        )
    return "\n".join(linhas) + "\n"


def _tabela_resumo(resumos: dict[str, ResumoDoGrupo]) -> str:
    linhas = [
        "| Grupo | Dias | Compradores/dia | GMV/dia | Comissão total | Cashback total | Margem total | Margem/dia | Ticket médio | Taxa de cashback | Take rate | ROI do cashback |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in resumos.values():
        linhas.append(
            f"| **{s.grupo}** | {s.dias} | {s.compradores_media_dia:,.1f} | "
            f"{_moeda(s.vendas_media_dia)} | {_moeda(s.comissao_total)} | "
            f"{_moeda(s.cashback_total)} | {_moeda(s.margem_total)} | "
            f"{_moeda(s.margem_media_dia)} | {_moeda(s.ticket_medio)} | "
            f"{_percentual(s.taxa_cashback)} | {_percentual(s.taxa_comissao)} | "
            f"{s.roi_cashback:.2f}x |"
        )
    return "\n".join(linhas) + "\n"


def montar_relatorio(
    *,
    caminho_dataset: str,
    nome_teste: str,
    descricao_teste: str,
    parceiro: str,
    data_min,
    data_max,
    resumos: dict[str, ResumoDoGrupo],
    testes_margem: list[TesteEntreGrupos],
    testes_compradores: list[TesteEntreGrupos],
    testes_gmv: list[TesteEntreGrupos],
    decisao: Decisao,
    relatorio_limpeza: RelatorioDeLimpeza,
    grafico_nome_arquivo: str,
    caminho_saida: str,
) -> str:
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_grupos = len(resumos)

    md = []
    md.append(f"# Relatório de Teste A/B — {nome_teste}")
    md.append("")
    md.append(f"**Parceiro:** {parceiro}  ")
    md.append(f"**Período analisado:** {data_min.date()} a {data_max.date()} ({(data_max - data_min).days + 1} dias)  ")
    md.append(f"**Grupos comparados:** {n_grupos} ({', '.join(resumos.keys())})  ")
    md.append(f"**Arquivo fonte:** `{os.path.basename(caminho_dataset)}`  ")
    md.append(f"**Gerado em:** {agora}  ")
    md.append("")
    md.append("## Sobre o teste")
    md.append(descricao_teste)
    md.append("")

    md.append("## Recomendação")
    md.append("")
    if decisao.conclusivo:
        md.append(f"### Escalar **{decisao.vencedor}** para 100% do tráfego.")
    else:
        md.append(f"### Resultado inconclusivo — manter **{decisao.baseline}** (baseline) rodando por enquanto.")
    md.append("")
    md.append("**Por quê:**")
    for r in decisao.justificativa:
        md.append(f"- {r}")
    md.append("")
    if decisao.tradeoffs:
        md.append("**Trade-offs que valem a pena o gestor saber:**")
        for t in decisao.tradeoffs:
            md.append(f"- {t}")
        md.append("")
    if decisao.ressalvas:
        md.append("**Ressalvas / limites dessa análise:**")
        for c in decisao.ressalvas:
            md.append(f"- {c}")
        md.append("")

    md.append("## Resumo por grupo")
    md.append("")
    md.append(_tabela_resumo(resumos))
    md.append("")
    md.append(f"![Margem e volume por grupo]({grafico_nome_arquivo})")
    md.append("")

    md.append("## Testes de significância")
    md.append("")
    md.append("### Margem diária (comissão − cashback) — a métrica que decide")
    md.append(_tabela_testes(testes_margem))
    md.append("")
    md.append("### Compradores por dia (volume)")
    md.append(_tabela_testes(testes_compradores))
    md.append("")
    md.append("### GMV (vendas totais) por dia")
    md.append(_tabela_testes(testes_gmv))
    md.append("")

    md.append("## Qualidade dos dados")
    md.append("")
    md.append(f"- Linhas lidas: {relatorio_limpeza.linhas_lidas} | Linhas válidas depois da limpeza: {relatorio_limpeza.linhas_validas}")
    if relatorio_limpeza.duplicatas_removidas:
        md.append(f"- Duplicatas removidas: {relatorio_limpeza.duplicatas_removidas}")
    if relatorio_limpeza.linhas_com_campo_critico_ausente:
        md.append(f"- Linhas descartadas por campo essencial faltando: {relatorio_limpeza.linhas_com_campo_critico_ausente}")
    if relatorio_limpeza.falhas_ao_converter_moeda:
        md.append(f"- Valores monetários que não consegui interpretar: {relatorio_limpeza.falhas_ao_converter_moeda}")
    if relatorio_limpeza.avisos:
        for aviso in relatorio_limpeza.avisos:
            md.append(f"- {aviso}")
    if not (relatorio_limpeza.avisos or relatorio_limpeza.duplicatas_removidas or relatorio_limpeza.linhas_com_campo_critico_ausente):
        md.append("- Não encontrei nenhum problema de qualidade nesse dataset.")
    md.append("")

    md.append("---")
    md.append("_Relatório gerado automaticamente pela solução de análise de testes A/B de cashback._")

    conteudo = "\n".join(md)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        f.write(conteudo)
    return conteudo
