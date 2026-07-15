"""
decision.py

Aqui é onde a análise vira uma decisão de fato -- essa é a parte que eu mais
me preocupei em deixar bem justificada, porque de nada adianta ter um monte
de teste estatístico bonito se no final o script não consegue responder
"qual variante eu escalo pra 100%?" de um jeito que um gestor confie.

O raciocínio que segui:

1. A métrica que decide é MARGEM (comissão - cashback), não volume. Reparei
   olhando os 3 datasets que isso importa MUITO: em todos eles, o grupo com
   cashback mais alto trouxe mais compradores e mais GMV, só que a margem
   caiu -- ou seja, dar mais cashback funcionou pra crescer volume, mas
   destruiu lucro na mesma proporção (ou mais). Se eu tivesse decidido só
   olhando "quem vendeu mais", teria recomendado exatamente o oposto do que
   faz sentido financeiramente.

2. A regra é assimétrica de propósito, que é como eu entendo que teste A/B
   deveria funcionar na prática: pra MANTER o que já está rodando (o
   baseline) eu não exijo prova estatística nenhuma -- se o baseline já tem
   a maior margem, não tem "vantagem de ninguém" pra provar. Mas pra TROCAR
   de variante e escalar outra coisa pra 100% do tráfego, aí sim eu exijo
   que a vantagem seja estatisticamente significativa. Trocar de variante
   tem custo (operacional, de risco, de credibilidade do teste), então o
   critério pra trocar tem que ser mais rígido do que o critério pra manter.

3. Mesmo quando a decisão já está tomada pela margem, eu ainda reporto se a
   variante escolhida perde em volume (compradores/GMV) pra alguma outra --
   isso é informação que o gestor pode querer saber, por exemplo se o
   objetivo do trimestre for ganhar market share e não só lucro imediato.
"""
from __future__ import annotations

from dataclasses import dataclass

from .metrics import ResumoDoGrupo, TesteEntreGrupos


@dataclass
class Decisao:
    vencedor: str
    baseline: str
    conclusivo: bool
    justificativa: list[str]
    tradeoffs: list[str]
    ressalvas: list[str]


def decidir(
    resumos: dict[str, ResumoDoGrupo],
    baseline: str,
    testes_margem: list[TesteEntreGrupos],
    testes_compradores: list[TesteEntreGrupos],
    testes_gmv: list[TesteEntreGrupos],
    desbalanceamento_detectado: bool,
) -> Decisao:
    justificativa = []
    tradeoffs = []
    ressalvas = []

    if desbalanceamento_detectado:
        ressalvas.append(
            "Os grupos não têm o mesmo número de dias observados -- isso pode ser sinal de "
            "problema na coleta ou na forma como o tráfego foi dividido entre as variantes. "
            "Vale checar antes de confiar 100% no resultado."
        )

    grupos_ordenados = sorted(resumos.values(), key=lambda g: g.margem_media_dia, reverse=True)
    melhor_em_margem = grupos_ordenados[0]

    # deixo registrado como cada variante se compara ao baseline, mesmo a que "perdeu",
    # porque isso é útil pro gestor entender o cenário completo, não só o resultado final.
    # importante: só mostro aqui os pares que envolvem o baseline de verdade -- os testes
    # também recebem comparações entre variantes não-baseline (usadas só pro trade-off
    # mais abaixo), e rotular essas como "(baseline)" seria enganoso.
    for teste in testes_margem:
        if teste.grupo_a != baseline:
            continue
        justificativa.append(
            f"Margem/dia -- {teste.grupo_a} (baseline) vs {teste.grupo_b}: diferença de "
            f"R$ {teste.diferenca:,.2f}/dia ({teste.diferenca_pct:+.1f}%), "
            f"{'estatisticamente significativa' if teste.significativo else 'NÃO significativa'} "
            f"(p_welch={teste.p_valor_welch:.4f}, p_mannwhitney={teste.p_valor_mannwhitney:.4f})."
        )

    if melhor_em_margem.grupo == baseline:
        # o próprio baseline já é a melhor opção -- não preciso provar nada pra manter ele rodando
        conclusivo = True
        vencedor = baseline
        justificativa.insert(0,
            f"O baseline ('{baseline}') já é a variante com maior margem média por dia "
            f"(R$ {melhor_em_margem.margem_media_dia:,.2f}). Nenhuma outra variante superou ele "
            "em margem, então não existe vantagem alguma pra provar estatisticamente."
        )
    else:
        # aqui sim eu preciso do teste estatístico pra justificar a troca
        teste_vs_baseline = next(
            (t for t in testes_margem if t.grupo_a == baseline and t.grupo_b == melhor_em_margem.grupo),
            None,
        )
        troca_e_justificada = (
            teste_vs_baseline is not None
            and teste_vs_baseline.significativo
            and teste_vs_baseline.diferenca > 0
        )
        if troca_e_justificada:
            conclusivo = True
            vencedor = melhor_em_margem.grupo
            justificativa.insert(0,
                f"'{melhor_em_margem.grupo}' tem a maior margem média por dia "
                f"(R$ {melhor_em_margem.margem_media_dia:,.2f}) e a vantagem sobre o baseline "
                f"('{baseline}') é estatisticamente significativa "
                f"(+{teste_vs_baseline.diferenca_pct:.1f}%, p_welch={teste_vs_baseline.p_valor_welch:.4f})."
            )
        else:
            conclusivo = False
            vencedor = baseline
            justificativa.insert(0,
                f"'{melhor_em_margem.grupo}' teve a maior margem média observada "
                f"(R$ {melhor_em_margem.margem_media_dia:,.2f}), mas essa vantagem sobre o baseline "
                f"('{baseline}') NÃO é estatisticamente significativa -- pode muito bem ser ruído "
                "da amostra. Não dá pra considerar esse resultado conclusivo pra justificar a troca."
            )
            ressalvas.append(
                "Recomendo manter o baseline em produção e rodar o teste por mais tempo (ou com mais "
                "tráfego) antes de escalar qualquer variante pra 100%."
            )

    # trade-off de volume: a variante escolhida pode ter margem melhor mas vender menos
    # que alguma outra -- acho importante deixar isso explícito, não escondido dentro do número
    outros_grupos = [g for g in resumos if g != vencedor]
    for grupo in outros_grupos:
        for rotulo, testes in (("compradores/dia", testes_compradores), ("GMV/dia", testes_gmv)):
            teste = next((t for t in testes if {t.grupo_a, t.grupo_b} == {vencedor, grupo}), None)
            if teste is None:
                continue
            diferenca = teste.diferenca if teste.grupo_b == vencedor else -teste.diferenca
            if teste.significativo and diferenca < 0:
                tradeoffs.append(
                    f"'{vencedor}' vende significativamente MENOS {rotulo} do que '{grupo}' "
                    f"(diferença de {diferenca:,.2f}/dia). Ou seja, a variante mais lucrativa "
                    "também é a que traz menos volume -- vale o gestor pesar se o objetivo agora "
                    "é lucro ou crescimento/alcance."
                )

    ressalvas.append(
        "Os dados são agregados por dia, não por usuário -- os testes estatísticos comparam as "
        "séries diárias entre variantes. É uma aproximação razoável quando a divisão de tráfego "
        "entre grupos é estável ao longo do teste, mas não substitui um teste no nível de usuário."
    )
    ressalvas.append(
        "Essa análise não modela sazonalidade (dia da semana, feriado, campanha concorrente "
        "rodando ao mesmo tempo) nem efeito de longo prazo do cashback sobre retenção/LTV -- "
        "só olha pro período em que o teste rodou."
    )

    return Decisao(
        vencedor=vencedor,
        baseline=baseline,
        conclusivo=conclusivo,
        justificativa=justificativa,
        tradeoffs=tradeoffs,
        ressalvas=ressalvas,
    )
