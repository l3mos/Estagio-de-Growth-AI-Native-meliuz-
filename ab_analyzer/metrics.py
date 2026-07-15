"""
metrics.py

Esse módulo calcula as métricas por grupo e roda os testes de significância.

Um ponto importante que percebi olhando os dados: eles são agregados por
DIA, não por usuário. Ou seja, não tenho "usuário X comprou ou não comprou"
-- tenho "no dia Y, o grupo Z teve N compradores, R$ tal de comissão etc".
Isso muda a forma de testar estatisticamente: em vez do teste clássico de
proporção (que é o que todo mundo pensa quando ouve "teste A/B", tipo
taxa de conversão por usuário), aqui eu comparo as SÉRIES DIÁRIAS de cada
métrica entre os grupos. Cada dia vira uma "observação" da variante.

Isso é uma aproximação razoável desde que a alocação de tráfego entre os
grupos seja estável ao longo do tempo (o que parece ser o caso -- os 3
datasets têm o mesmo período pra todos os grupos, sem grupo "entrando"
depois). Mas é uma limitação real que deixo documentada no relatório, porque
não seria honesto vender isso como equivalente a um teste no nível de
usuário.

Métrica que uso como foco principal: MARGEM = comissão - cashback. É o
lucro bruto que o Méliuz realmente embolsa naquele teste. Achei importante
não focar só em "quantos compradores" ou "quanto de GMV", porque um
cashback mais alto quase sempre atrai mais gente e mais venda -- isso por
si só não significa que valeu a pena financeiramente.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass
class ResumoDoGrupo:
    grupo: str
    dias: int
    compradores_total: int
    compradores_media_dia: float
    vendas_total: float
    vendas_media_dia: float
    comissao_total: float
    cashback_total: float
    margem_total: float
    margem_media_dia: float
    ticket_medio: float
    taxa_cashback: float   # cashback / vendas totais -- proxy do % de cashback dado
    taxa_comissao: float   # comissao / vendas totais -- take rate do parceiro
    taxa_margem: float     # margem / vendas totais
    roi_cashback: float    # cada R$1 de cashback trouxe quanto de comissão de volta


@dataclass
class TesteEntreGrupos:
    grupo_a: str
    grupo_b: str
    metrica: str
    media_a: float
    media_b: float
    diferenca: float
    diferenca_pct: float
    p_valor_welch: float
    p_valor_mannwhitney: float
    significativo: bool
    ic95_baixo: float
    ic95_alto: float


def resumir_grupo(dados_do_grupo: pd.DataFrame, nome_do_grupo: str) -> ResumoDoGrupo:
    d = dados_do_grupo
    vendas_total = d["vendas_totais"].sum()
    comissao_total = d["comissao"].sum()
    cashback_total = d["cashback"].sum()
    margem_total = comissao_total - cashback_total
    compradores_total = int(d["compradores"].sum())

    return ResumoDoGrupo(
        grupo=nome_do_grupo,
        dias=len(d),
        compradores_total=compradores_total,
        compradores_media_dia=d["compradores"].mean(),
        vendas_total=vendas_total,
        vendas_media_dia=d["vendas_totais"].mean(),
        comissao_total=comissao_total,
        cashback_total=cashback_total,
        margem_total=margem_total,
        margem_media_dia=(d["comissao"] - d["cashback"]).mean(),
        ticket_medio=(vendas_total / compradores_total) if compradores_total else float("nan"),
        taxa_cashback=(cashback_total / vendas_total) if vendas_total else float("nan"),
        taxa_comissao=(comissao_total / vendas_total) if vendas_total else float("nan"),
        taxa_margem=(margem_total / vendas_total) if vendas_total else float("nan"),
        roi_cashback=(comissao_total / cashback_total) if cashback_total else float("nan"),
    )


def bootstrap_ic_diferenca(a: np.ndarray, b: np.ndarray, n_repeticoes: int = 5000, seed: int = 42):
    """
    IC 95% pra diferença de médias (b - a), via bootstrap. Preferi bootstrap
    a uma fórmula fechada porque não quero assumir normalidade dos dados
    diários -- com poucos dias por grupo (45 a 92, dependendo do dataset)
    isso pode não ser uma suposição segura.
    """
    rng = np.random.default_rng(seed)
    diferencas = np.empty(n_repeticoes)
    for i in range(n_repeticoes):
        amostra_a = rng.choice(a, size=len(a), replace=True)
        amostra_b = rng.choice(b, size=len(b), replace=True)
        diferencas[i] = amostra_b.mean() - amostra_a.mean()
    return float(np.percentile(diferencas, 2.5)), float(np.percentile(diferencas, 97.5))


def comparar_grupos(df: pd.DataFrame, baseline: str, coluna_metrica: str, nome_metrica: str) -> list[TesteEntreGrupos]:
    """
    Compara cada grupo diferente do baseline contra o baseline, numa métrica
    diária específica. Uso dois testes em paralelo porque eles têm premissas
    diferentes e prefiro só confiar quando os dois concordam:

    - Welch's t-test: compara médias, não assume variâncias iguais entre os
      grupos (o teste clássico assume, e isso quase nunca é verdade em dados
      de negócio de verdade).
    - Mann-Whitney U: não-paramétrico, olha pra ordem dos valores em vez da
      média -- serve como checagem caso a distribuição diária tenha outlier
      ou seja bem assimétrica (o que rolou, por exemplo, com dias de fim de
      semana puxando os números pra baixo).

    Só marco como "significativo" quando os DOIS testes dão p < 0.05.
    """
    resultados = []
    serie_baseline = df.loc[df["grupo"] == baseline, coluna_metrica].dropna().to_numpy()

    for grupo in sorted(df["grupo"].unique()):
        if grupo == baseline:
            continue
        serie_grupo = df.loc[df["grupo"] == grupo, coluna_metrica].dropna().to_numpy()
        if len(serie_baseline) < 2 or len(serie_grupo) < 2:
            continue  # não dá pra testar com menos de 2 pontos

        estat_t, p_welch = stats.ttest_ind(serie_grupo, serie_baseline, equal_var=False)
        try:
            _, p_mw = stats.mannwhitneyu(serie_grupo, serie_baseline, alternative="two-sided")
        except ValueError:
            # acontece se as duas séries forem idênticas -- não deveria rolar com dados
            # de venda de verdade, mas deixo o try/except pra não quebrar em caso de teste sintético
            p_mw = float("nan")

        ic_baixo, ic_alto = bootstrap_ic_diferenca(serie_baseline, serie_grupo)
        media_a, media_b = serie_baseline.mean(), serie_grupo.mean()
        diferenca = media_b - media_a
        diferenca_pct = (diferenca / media_a * 100) if media_a else float("nan")

        resultados.append(TesteEntreGrupos(
            grupo_a=baseline,
            grupo_b=grupo,
            metrica=nome_metrica,
            media_a=media_a,
            media_b=media_b,
            diferenca=diferenca,
            diferenca_pct=diferenca_pct,
            p_valor_welch=p_welch,
            p_valor_mannwhitney=p_mw,
            significativo=bool(p_welch < 0.05 and p_mw < 0.05),
            ic95_baixo=ic_baixo,
            ic95_alto=ic_alto,
        ))
    return resultados


def checar_desbalanceamento_de_dias(df: pd.DataFrame) -> tuple[bool, dict]:
    """
    No teste A/B "de livro-texto" (usuário por usuário) existe uma checagem
    chamada Sample Ratio Mismatch: se um grupo recebeu muito mais ou muito
    menos tráfego do que deveria, isso é sinal de bug na randomização e
    invalida a comparação. Aqui não tenho tráfego por usuário, mas dá pra
    fazer uma versão adaptada olhando o número de DIAS observados por grupo
    -- se um grupo tem muito menos dias de dado que os outros, também é
    motivo pra desconfiar do resultado antes de recomendar qualquer coisa.
    """
    contagem = df.groupby("grupo")["data"].count()
    esperado = contagem.mean()
    qui2 = float(((contagem - esperado) ** 2 / esperado).sum())
    p_valor = float(1 - stats.chi2.cdf(qui2, df=len(contagem) - 1)) if len(contagem) > 1 else 1.0
    return p_valor < 0.01, {"contagem_por_grupo": contagem.to_dict(), "p_valor": p_valor}
