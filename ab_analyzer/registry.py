"""
registry.py

Registra cada teste analisado numa "planilha" de acompanhamento -- a ideia
é que, com o tempo, alguém do time consiga abrir esse arquivo e ver todos os
testes já rodados, sem precisar caçar relatório por relatório.

Fiz em duas camadas:

1. CSV local (registry/tracking_sheet.csv) -- sempre funciona, não depende
   de internet nem de credencial nenhuma. É o que o enunciado pede como
   mínimo, e também é o que eu uso de "fonte de verdade" porque é portátil
   (dá pra abrir em qualquer lugar, inclusive importar direto no Sheets).

2. Google Sheets de verdade (opcional) -- se existir uma credencial de
   Service Account configurada via variável de ambiente, a mesma linha
   também é escrita ao vivo numa planilha do Google via gspread. Se não
   tiver credencial configurada (que é o meu caso rodando isso localmente
   sem ter subido uma Service Account ainda), essa parte só avisa no
   terminal e segue o baile -- o CSV continua sendo escrito normalmente.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime

COLUNAS_DA_PLANILHA = [
    "data_registro",
    "nome_teste",
    "descricao",
    "parceiro",
    "periodo_inicio",
    "periodo_fim",
    "grupos",
    "baseline",
    "vencedor",
    "conclusivo",
    "margem_dia_vencedor",
    "lift_margem_vs_baseline_pct",
    "resultado_resumo",
    "decisao",
    "link_relatorio",
]


def adicionar_linha_no_csv(linha: dict, caminho_csv: str) -> None:
    arquivo_ja_existe = os.path.exists(caminho_csv)
    os.makedirs(os.path.dirname(caminho_csv) or ".", exist_ok=True)
    with open(caminho_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUNAS_DA_PLANILHA)
        if not arquivo_ja_existe:
            writer.writeheader()
        writer.writerow({k: linha.get(k, "") for k in COLUNAS_DA_PLANILHA})


def tentar_escrever_no_google_sheets(linha: dict) -> bool:
    """
    Tenta escrever a mesma linha numa planilha Google Sheets real. Retorna
    False em vez de lançar exceção se não der certo -- não quero que a
    análise inteira falhe só porque o Sheets não está configurado.
    """
    caminho_credenciais = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON")
    id_planilha = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")

    if not caminho_credenciais or not id_planilha:
        print(
            "[registry] Google Sheets não configurado (falta GOOGLE_SHEETS_CREDENTIALS_JSON "
            "e/ou GOOGLE_SHEETS_SPREADSHEET_ID nas variáveis de ambiente). Seguindo só com o CSV."
        )
        return False

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        escopos = ["https://www.googleapis.com/auth/spreadsheets"]
        credenciais = Credentials.from_service_account_file(caminho_credenciais, scopes=escopos)
        cliente = gspread.authorize(credenciais)
        planilha = cliente.open_by_key(id_planilha)
        aba = planilha.sheet1

        if aba.row_count == 0 or not aba.get_all_values():
            aba.append_row(COLUNAS_DA_PLANILHA)
        aba.append_row([linha.get(k, "") for k in COLUNAS_DA_PLANILHA])
        print("[registry] Linha escrita com sucesso no Google Sheets.")
        return True
    except Exception as erro:  # não quero derrubar o script por causa disso
        print(f"[registry] Não consegui escrever no Google Sheets ({erro}). Seguindo só com o CSV.")
        return False


def registrar_teste(
    *,
    nome_teste: str,
    descricao: str,
    parceiro: str,
    data_min,
    data_max,
    grupos: list[str],
    baseline: str,
    vencedor: str,
    conclusivo: bool,
    margem_dia_vencedor: float,
    lift_pct: float,
    resultado_resumo: str,
    decisao_texto: str,
    link_relatorio: str,
    caminho_csv: str,
) -> dict:
    linha = {
        "data_registro": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "nome_teste": nome_teste,
        "descricao": descricao,
        "parceiro": parceiro,
        "periodo_inicio": str(data_min.date()),
        "periodo_fim": str(data_max.date()),
        "grupos": ", ".join(grupos),
        "baseline": baseline,
        "vencedor": vencedor,
        "conclusivo": "Sim" if conclusivo else "Não",
        "margem_dia_vencedor": f"{margem_dia_vencedor:.2f}",
        "lift_margem_vs_baseline_pct": f"{lift_pct:.1f}" if lift_pct == lift_pct else "N/A",
        "resultado_resumo": resultado_resumo,
        "decisao": decisao_texto,
        "link_relatorio": link_relatorio,
    }
    adicionar_linha_no_csv(linha, caminho_csv)
    tentar_escrever_no_google_sheets(linha)
    return linha
