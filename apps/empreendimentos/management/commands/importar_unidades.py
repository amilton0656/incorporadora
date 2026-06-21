import csv
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Empresa
from apps.empreendimentos.models import (
    Bloco, DesignacaoUnidade, Empreendimento, StatusUnidade, TipoUnidade, Unidade,
)

TIPOS_COMPLEMENTAR = {'Garagem', 'Hobby Box'}

TIPO_DESIGNACAO = {
    'Garagem': DesignacaoUnidade.GARAGEM_CARRO,
    'Hobby Box': DesignacaoUnidade.HOBBY_BOX,
}

TIPO_DESIGNACAO_LABEL = {
    'garagem carro': DesignacaoUnidade.GARAGEM_CARRO,
    'garagem moto': DesignacaoUnidade.GARAGEM_MOTO,
    'hobby box': DesignacaoUnidade.HOBBY_BOX,
}

TIPO_DESIGNACAO_PREFIXO = {
    'HB': DesignacaoUnidade.HOBBY_BOX,
    'M': DesignacaoUnidade.GARAGEM_MOTO,
    'G': DesignacaoUnidade.GARAGEM_CARRO,
}


def _inferir_tipo_designacao(numero):
    """Infere o tipo de designação pelo prefixo do número (HB > M > G)."""
    upper = numero.upper()
    for prefixo, tipo in TIPO_DESIGNACAO_PREFIXO.items():
        if upper.startswith(prefixo):
            return tipo
    return None


def _parse_decimal(value):
    if not value or not value.strip():
        return None
    try:
        return Decimal(value.strip().replace(',', '.'))
    except InvalidOperation:
        return None


def _fix_encoding(content):
    """Corrige dupla codificação gerada pelo Excel (latin-1 bytes reinterpretados como UTF-8)."""
    try:
        return content.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return content


def _colunas_faltando(fieldnames, obrigatorias):
    return sorted(obrigatorias - set(fieldnames or []))


COLUNAS_UNIDADES = {
    'Empreendimento', 'Bloco', 'numero', 'ordem', 'adicionais', 'tipo',
    'tipologia', 'localizacao', 'area_privativa', 'area_privativa_acessoria',
    'area_comum', 'fracao_ideal', 'valor_tabela', 'status',
    'descricao1', 'descricao2', 'descricao3',
}

COLUNAS_VINCULOS = {'tipo', 'principal', 'complementar'}


class Command(BaseCommand):
    help = 'Importa unidades a partir de CSV (separador ;). Use --vinculos para vínculos.'

    def add_arguments(self, parser):
        parser.add_argument('arquivo', help='Caminho do arquivo CSV de unidades')
        parser.add_argument('--empresa', required=True, type=int, help='ID da empresa')
        parser.add_argument('--vinculos', help='Caminho do CSV de vínculos (colunas: tipo;principal;complementar;designacao_tipo)')
        parser.add_argument('--dry-run', action='store_true', help='Simula sem gravar no banco')

    def handle(self, *args, **options):
        try:
            empresa = Empresa.objects.get(pk=options['empresa'])
        except Empresa.DoesNotExist:
            raise CommandError(f"Empresa id={options['empresa']} não encontrada.")

        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write(self.style.WARNING('--- DRY RUN: nenhuma alteração será gravada ---'))

        with open(options['arquivo'], encoding='utf-8-sig') as f:
            content = _fix_encoding(f.read())

        reader = csv.DictReader(content.splitlines(), delimiter=';')
        faltando = _colunas_faltando(reader.fieldnames, COLUNAS_UNIDADES)
        if faltando:
            raise CommandError(f'CSV de unidades: coluna(s) ausente(s): {", ".join(faltando)}')

        rows = list(reader)
        criadas = atualizadas = erros = 0

        for i, row in enumerate(rows, start=2):
            try:
                emp_nome = row['Empreendimento'].strip()
                bloco_nome = row['Bloco'].strip()
                numero = row['numero'].strip()
                tipo_nome = row['tipo'].strip()
                status_nome = row['status'].strip()

                empreendimento = Empreendimento.objects.get(
                    empresa=empresa,
                    nome=emp_nome,
                )

                bloco, _ = Bloco.objects.get_or_create(
                    empreendimento=empreendimento,
                    nome=bloco_nome,
                    defaults={'ordem': 0},
                )

                categoria = (
                    TipoUnidade.COMPLEMENTAR
                    if tipo_nome in TIPOS_COMPLEMENTAR
                    else TipoUnidade.PRINCIPAL
                )
                tipo_obj, _ = TipoUnidade.objects.get_or_create(
                    empresa=empresa,
                    nome=tipo_nome,
                    defaults={'categoria': categoria},
                )

                status_obj, _ = StatusUnidade.objects.get_or_create(
                    empresa=empresa,
                    nome=status_nome,
                )

                campos = dict(
                    ordem=int(row.get('ordem') or 0),
                    adicionais=row.get('adicionais', '').strip(),
                    tipo=tipo_obj,
                    status=status_obj,
                    tipologia=row.get('tipologia', '').strip(),
                    localizacao=row.get('localizacao', '').strip(),
                    area_privativa=_parse_decimal(row.get('area_privativa')),
                    area_privativa_acessoria=_parse_decimal(row.get('area_privativa_acessoria')),
                    area_comum=_parse_decimal(row.get('area_comum')),
                    fracao_ideal=_parse_decimal(row.get('fracao_ideal')),
                    valor_tabela=_parse_decimal(row.get('valor_tabela')),
                    descricao_1=row.get('descricao1', '').strip(),
                    descricao_2=row.get('descricao2', '').strip(),
                    descricao_3=row.get('descricao3', '').strip(),
                )

                if not dry_run:
                    unidade, criada = Unidade.objects.update_or_create(
                        bloco=bloco,
                        numero=numero,
                        defaults=campos,
                    )
                    tipo_desig = TIPO_DESIGNACAO.get(tipo_nome)
                    if tipo_desig:
                        DesignacaoUnidade.objects.get_or_create(
                            unidade=unidade,
                            nome=numero,
                            defaults={'tipo': tipo_desig},
                        )
                    if criada:
                        criadas += 1
                    else:
                        atualizadas += 1
                else:
                    self.stdout.write(f'  {emp_nome} / {bloco_nome} / {numero} [{status_nome}]')

            except Empreendimento.DoesNotExist:
                self.stderr.write(self.style.ERROR(f'Linha {i}: empreendimento "{emp_nome}" não encontrado para empresa {empresa}.'))
                erros += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'Linha {i}: {e}'))
                erros += 1

        self.stdout.write(self.style.SUCCESS(
            f'Unidades — criadas: {criadas} | atualizadas: {atualizadas} | erros: {erros}'
        ))

        if options.get('vinculos'):
            self._importar_vinculos(options['vinculos'], empresa, dry_run)

    def _importar_vinculos(self, arquivo, empresa, dry_run):
        """
        CSV (separador ;):
            tipo;principal;complementar;designacao_tipo
            1;102;G15;
            2;101;G09;Garagem carro
            2;101;HB01;Hobby box

        tipo=1: matrículas diferentes → Unidade.unidade_principal (FK)
        tipo=2: mesma matrícula       → DesignacaoUnidade na unidade principal
        """
        processados = erros = 0

        with open(arquivo, encoding='utf-8-sig') as f:
            content = _fix_encoding(f.read())

        reader = csv.DictReader(content.splitlines(), delimiter=';')
        faltando = _colunas_faltando(reader.fieldnames, COLUNAS_VINCULOS)
        if faltando:
            raise CommandError(f'CSV de vínculos: coluna(s) ausente(s): {", ".join(faltando)}')

        for i, row in enumerate(reader, start=2):
            tipo = row.get('tipo', '').strip()
            num_princ = row.get('principal', '').strip()
            num_comp = row.get('complementar', '').strip()
            desig_label = row.get('designacao_tipo', '').strip()

            if tipo not in ('1', '2'):
                self.stderr.write(self.style.ERROR(f'Linha {i}: tipo inválido "{tipo}". Use 1 ou 2.'))
                erros += 1
                continue

            try:
                principal = Unidade.objects.get(
                    bloco__empreendimento__empresa=empresa,
                    numero=num_princ,
                )

                if tipo == '1':
                    complementar = Unidade.objects.get(
                        bloco__empreendimento__empresa=empresa,
                        numero=num_comp,
                    )
                    if not dry_run:
                        complementar.unidade_principal = principal
                        complementar.tipo_vinculo = Unidade.MATRICULA_PROPRIA
                        complementar.save(update_fields=['unidade_principal', 'tipo_vinculo'])
                    else:
                        self.stdout.write(f'  [tipo 1] {num_comp} → {num_princ} (matrícula própria)')

                else:  # tipo == '2'
                    if desig_label:
                        desig_tipo = TIPO_DESIGNACAO_LABEL.get(desig_label.lower())
                        if not desig_tipo:
                            self.stderr.write(self.style.ERROR(
                                f'Linha {i}: designacao_tipo inválido "{desig_label}". '
                                f'Use: {", ".join(TIPO_DESIGNACAO_LABEL)}'
                            ))
                            erros += 1
                            continue
                    else:
                        desig_tipo = _inferir_tipo_designacao(num_comp)
                        if not desig_tipo:
                            self.stderr.write(self.style.ERROR(
                                f'Linha {i}: não foi possível inferir designacao_tipo para "{num_comp}". '
                                f'Informe explicitamente ou use prefixo G, M ou HB.'
                            ))
                            erros += 1
                            continue

                    if not dry_run:
                        DesignacaoUnidade.objects.get_or_create(
                            unidade=principal,
                            nome=num_comp,
                            defaults={'tipo': desig_tipo},
                        )
                    else:
                        self.stdout.write(f'  [tipo 2] {num_comp} ({desig_label}) ← {num_princ} (mesma matrícula)')

                processados += 1

            except Unidade.DoesNotExist as e:
                self.stderr.write(self.style.ERROR(f'Linha {i}: {e}'))
                erros += 1

        self.stdout.write(self.style.SUCCESS(
            f'Vínculos — processados: {processados} | erros: {erros}'
        ))
