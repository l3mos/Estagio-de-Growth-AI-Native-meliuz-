"""
loader.py

Antes de qualquer análise, eu precisava ter certeza de que estava confiando
em números confiáveis. Na primeira olhada nos 3 CSVs os dados vieram bem
"redondos" (sem nulo, sem duplicata), mas não dava pra garantir que um
dataset novo, gerado por outra pessoa do time ou exportado de outro jeito,
viesse igual de limpo. Então esse módulo assume por padrão que o arquivo
PODE vir sujo e trata os problemas mais comuns que eu imaginei que
aconteceriam num export manual de planilha:

- valor em R$ ora com vírgula decimal, ora só com ponto de milhar
  (ex: "R$ 10.273" vs "R$ 1.234,56")
- espaço sobrando, acento faltando ou nome de coluna com case diferente
- linha duplicada (aconteceu comigo já em outra planilha de teste A/B)
- grupo escrito diferente em linhas diferentes ("grupo 1", "Grupo1 ")
- compradores/valores negativos (não existe venda negativa nesse contexto)
- data fora do padrão ISO
- dias "furados" no meio do teste (algum grupo sem observação num dia)

A ideia é nunca deixar o script quebrar só porque um CSV veio com uma linha
estranha -- em vez disso, ele limpa o que dá, descarta o que não dá pra
confiar, e REPORTA tudo isso no relatório final. Isso importa porque, se eu
simplesmente ignorasse os problemas, o gestor que ler o relatório não teria
como saber se a recomendação é confiável ou não.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field

import pandas as pd


def _remove_acentos(s: str) -> str:
    # normaliza "comissão" -> "comissao" pra facilitar comparação de nomes de coluna
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _nome_coluna_normalizado(c: str) -> str:
    return _remove_acentos(c).strip().lower()


REGEX_MOEDA = re.compile(r"[^0-9,.\-]")


def parse_valor_monetario(valor) -> float:
    """
    Converte uma string tipo "R$ 10.273" pra float. Escrevi essa função
    pensando nos dois formatos que mais aparecem em export de planilha
    brasileira: "1.234,56" (ponto = milhar, vírgula = decimal) e o formato
    americano "1,234.56". Como os datasets do teste não tinham centavos
    (sempre inteiro), tratei esse caso também -- "R$ 10.273" é 10273, não
    10.273 centavos de real.

    Se não der pra converter de jeito nenhum, retorna NaN em vez de estourar
    uma exceção -- prefiro descartar a linha depois e avisar no relatório do
    que derrubar a análise inteira por causa de um campo mal formatado.
    """
    if pd.isna(valor):
        return float("nan")
    if isinstance(valor, (int, float)):
        return float(valor)

    s = str(valor).strip()
    if s == "" or s.upper() in {"R$", "-", "N/A", "NA", "NULL"}:
        return float("nan")

    s = REGEX_MOEDA.sub("", s)
    if s in {"", "-"}:
        return float("nan")

    tem_virgula = "," in s
    tem_ponto = "." in s

    try:
        if tem_virgula and tem_ponto:
            # o último separador que aparece geralmente é o decimal
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")  # formato BR
            else:
                s = s.replace(",", "")  # formato US
        elif tem_virgula and not tem_ponto:
            # só decido que é decimal se tiver exatamente 2 casas depois da vírgula
            if re.search(r",\d{2}$", s):
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
        elif tem_ponto and not tem_virgula:
            # aqui é o caso mais chato: "10.273" é 10273 reais (milhar) ou
            # seria 10,273 (decimal)? Só assumo decimal se tiver exatamente
            # 2 dígitos depois do ponto e for o único ponto da string.
            if s.count(".") == 1 and re.search(r"\.\d{2}$", s):
                pass
            else:
                s = s.replace(".", "")
        return float(s)
    except ValueError:
        return float("nan")


@dataclass
class RelatorioDeLimpeza:
    """
    Guarda tudo que foi encontrado/corrigido na hora de carregar o CSV. A
    ideia é que essas informações apareçam no relatório final -- não faz
    sentido eu "consertar" o dado escondido e o gestor nunca saber que 3
    linhas foram descartadas, por exemplo.
    """
    caminho: str
    linhas_lidas: int = 0
    linhas_validas: int = 0
    duplicatas_removidas: int = 0
    linhas_com_campo_critico_ausente: int = 0
    linhas_com_valor_negativo: int = 0
    falhas_ao_converter_moeda: int = 0
    grupos_renomeados: dict = field(default_factory=dict)
    dias_faltantes_por_grupo: dict = field(default_factory=dict)
    avisos: list = field(default_factory=list)


def carregar_teste_ab(caminho: str) -> tuple[pd.DataFrame, RelatorioDeLimpeza]:
    """
    Lê o CSV do teste A/B e devolve um DataFrame padronizado + o relatório
    de limpeza acima. As colunas de saída são sempre as mesmas, independente
    de como o arquivo original estava nomeado:

        data, grupo, parceiro, compradores, comissao, cashback, vendas_totais
    """
    relatorio = RelatorioDeLimpeza(caminho=caminho)

    bruto = pd.read_csv(caminho, dtype=str, keep_default_na=True)
    relatorio.linhas_lidas = len(bruto)

    # mapeamento tolerante de nome de coluna -- se um dia vier "Comissão (R$)"
    # em vez de "comissão", ainda funciona
    colunas_normalizadas = {_nome_coluna_normalizado(c): c for c in bruto.columns}
    candidatos = {
        "data": ["data", "date"],
        "grupo": ["grupos de usuarios", "grupo", "variante", "group"],
        "parceiro": ["parceiro", "partner"],
        "compradores": ["compradores", "buyers", "usuarios"],
        "comissao": ["comissao", "commission"],
        "cashback": ["cashback"],
        "vendas": ["vendas totais", "gmv", "vendas"],
    }

    colunas_faltando = []
    mapa = {}
    for chave, opcoes in candidatos.items():
        achou = next((colunas_normalizadas[c] for c in opcoes if c in colunas_normalizadas), None)
        if achou is None:
            colunas_faltando.append(chave)
        else:
            mapa[chave] = achou

    if colunas_faltando:
        raise ValueError(
            f"O arquivo {caminho} não tem as colunas esperadas: {colunas_faltando}. "
            f"Colunas encontradas: {list(bruto.columns)}. Confere se é mesmo um export "
            "de teste A/B de cashback no schema padrão do Méliuz."
        )

    df = pd.DataFrame({
        "data": bruto[mapa["data"]],
        "grupo": bruto[mapa["grupo"]],
        "parceiro": bruto[mapa["parceiro"]],
        "compradores": bruto[mapa["compradores"]],
        "comissao": bruto[mapa["comissao"]],
        "cashback": bruto[mapa["cashback"]],
        "vendas_totais": bruto[mapa["vendas"]],
    })

    # --- nomes de grupo: tira espaço duplicado e padroniza capitalização ---
    df["grupo"] = df["grupo"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    mapa_grupo = {g: g.title() for g in df["grupo"].unique()}
    renomeados = {k: v for k, v in mapa_grupo.items() if k != v}
    if renomeados:
        relatorio.grupos_renomeados = renomeados
        relatorio.avisos.append(f"Padronizei o nome de alguns grupos: {renomeados}")
    df["grupo"] = df["grupo"].map(mapa_grupo)

    df["parceiro"] = df["parceiro"].astype(str).str.strip()

    # --- data ---
    df["data"] = pd.to_datetime(df["data"], errors="coerce", format="mixed")
    n_datas_invalidas = df["data"].isna().sum()
    if n_datas_invalidas:
        relatorio.avisos.append(f"{n_datas_invalidas} linha(s) tinham data que eu não consegui interpretar -- descartei.")

    # --- valores monetários ---
    for coluna in ["comissao", "cashback", "vendas_totais"]:
        nulos_antes = df[coluna].isna().sum()
        df[coluna] = df[coluna].apply(parse_valor_monetario)
        nulos_depois = df[coluna].isna().sum()
        if nulos_depois > nulos_antes:
            relatorio.falhas_ao_converter_moeda += int(nulos_depois - nulos_antes)

    df["compradores"] = pd.to_numeric(df["compradores"], errors="coerce")

    # --- duplicata exata (linha repetida igualzinha) ---
    n_antes = len(df)
    df = df.drop_duplicates(subset=["data", "grupo", "parceiro", "compradores", "comissao", "cashback", "vendas_totais"])
    relatorio.duplicatas_removidas = n_antes - len(df)

    # --- linha com campo crítico faltando não dá pra usar, então cai fora ---
    n_antes = len(df)
    campo_critico_ausente = df[["data", "grupo", "compradores", "comissao", "cashback", "vendas_totais"]].isna().any(axis=1)
    if campo_critico_ausente.any():
        relatorio.avisos.append(
            f"{campo_critico_ausente.sum()} linha(s) descartadas por terem algum campo essencial vazio/ilegível."
        )
    df = df[~campo_critico_ausente].copy()
    relatorio.linhas_com_campo_critico_ausente = n_antes - len(df)

    # --- valor negativo não faz sentido de negócio (não existe -5 compradores) ---
    n_antes = len(df)
    negativo = (df["compradores"] < 0) | (df["vendas_totais"] < 0) | (df["cashback"] < 0) | (df["comissao"] < 0)
    if negativo.any():
        relatorio.avisos.append(f"{negativo.sum()} linha(s) tinham valor negativo (impossível) e foram descartadas.")
    df = df[~negativo].copy()
    relatorio.linhas_com_valor_negativo = n_antes - len(df)

    zero_vendas = df["vendas_totais"] == 0
    if zero_vendas.any():
        relatorio.avisos.append(
            f"{zero_vendas.sum()} linha(s) com vendas totais = 0 -- mantive a linha, mas as "
            "taxas derivadas (cashback/vendas etc.) vão ficar como NaN pra esses dias."
        )

    # --- checagem de "buraco" no calendário do teste ---
    # se um grupo tem dias faltando no meio do período, isso pode ser um sinal
    # de problema de coleta (ou de que o teste não rodou igual pra todo mundo)
    for grupo, sub in df.groupby("grupo"):
        periodo_completo = pd.date_range(sub["data"].min(), sub["data"].max(), freq="D")
        dias_faltando = periodo_completo.difference(sub["data"])
        if len(dias_faltando) > 0:
            relatorio.dias_faltantes_por_grupo[grupo] = len(dias_faltando)
            relatorio.avisos.append(
                f"Grupo '{grupo}' tem {len(dias_faltando)} dia(s) sem observação dentro do período do teste."
            )

    df = df.sort_values(["grupo", "data"]).reset_index(drop=True)
    relatorio.linhas_validas = len(df)

    if df["grupo"].nunique() < 2:
        raise ValueError(
            f"Depois de limpar, sobrou só {df['grupo'].nunique()} grupo(s) em {caminho}. "
            "Preciso de pelo menos 2 grupos pra comparar alguma coisa."
        )

    return df, relatorio


if __name__ == "__main__":
    # rodar direto esse arquivo é útil só pra debugar a limpeza isoladamente
    df, rel = carregar_teste_ab(sys.argv[1])
    print(df.head())
    print(rel)
