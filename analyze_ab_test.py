#!/usr/bin/env python3
"""
analyze_ab_test.py

Esse é o ponto de entrada único da solução. A ideia do teste técnico era
construir algo reutilizável, então em vez de escrever um script "descartável"
por dataset, fiz um CLI genérico que recebe o caminho do CSV como parâmetro
e processa qualquer um dos 3 datasets sem eu precisar tocar em código --
só muda o --file.

Exemplo de uso:

    python analyze_ab_test.py \
        --file data/dataset_01_parceiroA.csv \
        --test-name "Cashback Parceiro A" \
        --test-description "Teste de 3 níveis de cashback no Parceiro A."

Se quiser rodar isso através de um agente de IA (Claude Code, Cursor,
etc.), o contrato de como o agente deve chamar esse script está descrito em
AGENTS.md -- assim dá pra pedir "analisa esse novo teste x" em linguagem
natural e o agente sabe exatamente o que rodar.
"""
from __future__ import annotations

import argparse
import os
import sys

from ab_analyzer.decision import decidir
from ab_analyzer.loader import carregar_teste_ab
from ab_analyzer.metrics import checar_desbalanceamento_de_dias, comparar_grupos, resumir_grupo
from ab_analyzer.registry import registrar_teste
from ab_analyzer.report import gerar_grafico, montar_relatorio


def slugificar(texto: str) -> str:
    # transforma "Cashback Parceiro A" em "cashback_parceiro_a" pra usar como
    # nome de arquivo sem espaço nem acento
    return "".join(c if c.isalnum() else "_" for c in texto.strip().lower()).strip("_")


def main():
    parser = argparse.ArgumentParser(
        description="Analisa um teste A/B de cashback e recomenda qual variante escalar pra 100% do tráfego."
    )
    parser.add_argument("--file", required=True, help="Caminho do CSV do teste A/B.")
    parser.add_argument("--test-name", default=None, help="Nome do teste (se não passar, uso o nome do arquivo).")
    parser.add_argument("--test-description", default="", help="Contexto do teste -- o que está sendo testado e por quê.")
    parser.add_argument("--baseline", default=None, help="Grupo baseline (se não passar, uso o primeiro em ordem alfabética, tipo 'Grupo 1').")
    parser.add_argument("--reports-dir", default="reports", help="Pasta onde salvar o relatório .md e o gráfico.")
    parser.add_argument("--registry-csv", default="registry/tracking_sheet.csv", help="CSV da planilha de acompanhamento.")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"Não achei o arquivo: {args.file}", file=sys.stderr)
        sys.exit(1)

    nome_teste = args.test_name or os.path.splitext(os.path.basename(args.file))[0]
    slug = slugificar(nome_teste)

    print(f"[1/6] Lendo e limpando {args.file} ...")
    df, relatorio_limpeza = carregar_teste_ab(args.file)
    print(f"      {relatorio_limpeza.linhas_validas}/{relatorio_limpeza.linhas_lidas} linhas ficaram válidas "
          f"depois da limpeza ({len(relatorio_limpeza.avisos)} aviso(s)).")

    grupos = sorted(df["grupo"].unique())
    baseline = args.baseline or grupos[0]
    if baseline not in grupos:
        print(f"O baseline '{baseline}' não existe nos dados. Grupos disponíveis: {grupos}", file=sys.stderr)
        sys.exit(1)

    parceiro = df["parceiro"].iloc[0]
    data_min, data_max = df["data"].min(), df["data"].max()

    print(f"[2/6] Calculando métricas por grupo ({len(grupos)} grupos, baseline='{baseline}') ...")
    df["margem"] = df["comissao"] - df["cashback"]
    resumos = {g: resumir_grupo(df[df["grupo"] == g], g) for g in grupos}

    print("[3/6] Rodando os testes de significância (Welch + Mann-Whitney + IC via bootstrap) ...")
    testes_margem = comparar_grupos(df, baseline, "margem", "Margem/dia (R$)")
    testes_compradores = comparar_grupos(df, baseline, "compradores", "Compradores/dia")
    testes_gmv = comparar_grupos(df, baseline, "vendas_totais", "GMV/dia (R$)")
    desbalanceamento_detectado, _ = checar_desbalanceamento_de_dias(df)

    # o motor de decisão às vezes precisa comparar duas variantes que NÃO são o baseline
    # (por exemplo, checar se a vencedora perde volume pra uma terceira variante)
    todos_testes_margem = list(testes_margem)
    todos_testes_compradores = list(testes_compradores)
    todos_testes_gmv = list(testes_gmv)
    for i, g1 in enumerate(grupos):
        for g2 in grupos[i + 1:]:
            if baseline in (g1, g2):
                continue  # esse par já está coberto acima
            subconjunto = df[df["grupo"].isin([g1, g2])]
            todos_testes_margem += comparar_grupos(subconjunto, g1, "margem", "Margem/dia (R$)")
            todos_testes_compradores += comparar_grupos(subconjunto, g1, "compradores", "Compradores/dia")
            todos_testes_gmv += comparar_grupos(subconjunto, g1, "vendas_totais", "GMV/dia (R$)")

    print("[4/6] Decidindo qual variante recomendar ...")
    decisao = decidir(resumos, baseline, todos_testes_margem, todos_testes_compradores, todos_testes_gmv, desbalanceamento_detectado)

    print("[5/6] Montando relatório e gráfico ...")
    os.makedirs(args.reports_dir, exist_ok=True)
    nome_grafico = f"{slug}_chart.png"
    caminho_grafico = os.path.join(args.reports_dir, nome_grafico)
    gerar_grafico(resumos, caminho_grafico, titulo=nome_teste)

    caminho_relatorio = os.path.join(args.reports_dir, f"{slug}.md")
    montar_relatorio(
        caminho_dataset=args.file,
        nome_teste=nome_teste,
        descricao_teste=args.test_description or "(nenhuma descrição foi passada)",
        parceiro=parceiro,
        data_min=data_min,
        data_max=data_max,
        resumos=resumos,
        testes_margem=testes_margem,
        testes_compradores=testes_compradores,
        testes_gmv=testes_gmv,
        decisao=decisao,
        relatorio_limpeza=relatorio_limpeza,
        grafico_nome_arquivo=nome_grafico,
        caminho_saida=caminho_relatorio,
    )

    print("[6/6] Registrando na planilha de acompanhamento ...")
    resumo_vencedor = resumos[decisao.vencedor]
    resumo_baseline = resumos[baseline]
    lift_pct = (
        (resumo_vencedor.margem_media_dia - resumo_baseline.margem_media_dia)
        / abs(resumo_baseline.margem_media_dia) * 100
        if resumo_baseline.margem_media_dia else float("nan")
    )
    resultado_resumo = (
        f"Margem/dia: {', '.join(f'{g}=R${s.margem_media_dia:,.0f}' for g, s in resumos.items())}. "
        f"Compradores/dia: {', '.join(f'{g}={s.compradores_media_dia:,.0f}' for g, s in resumos.items())}."
    )
    decisao_texto = (
        f"Escalar {decisao.vencedor} para 100% do tráfego."
        if decisao.conclusivo else
        f"Inconclusivo -- manter {baseline} (baseline) e rodar o teste por mais tempo."
    )
    registrar_teste(
        nome_teste=nome_teste,
        descricao=args.test_description or "(nenhuma descrição foi passada)",
        parceiro=parceiro,
        data_min=data_min,
        data_max=data_max,
        grupos=grupos,
        baseline=baseline,
        vencedor=decisao.vencedor,
        conclusivo=decisao.conclusivo,
        margem_dia_vencedor=resumo_vencedor.margem_media_dia,
        lift_pct=lift_pct,
        resultado_resumo=resultado_resumo,
        decisao_texto=decisao_texto,
        link_relatorio=caminho_relatorio,
        caminho_csv=args.registry_csv,
    )

    print()
    print("=" * 70)
    print(f"Pronto! Relatório em: {caminho_relatorio}")
    print(f"Recomendação: {decisao_texto}")
    print(f"Planilha atualizada em: {args.registry_csv}")
    print("=" * 70)


if __name__ == "__main__":
    main()