import sys
import csv
import re
import operator
import os
from math import ceil, inf
from statistics import median
from lib.prediction_class import *
import yaml

csv.field_size_limit(sys.maxsize)

class OutputParser(metaclass=ABCMeta):
    def __init__(self, **kwargs):
        self.input_iedb_files        = kwargs['input_iedb_files']
        self.input_tsv_file          = kwargs['input_tsv_file']
        self.key_file                = kwargs['key_file']
        self.output_file             = kwargs['output_file']
        self.sample_name             = kwargs['sample_name']

    def parse_input_tsv_file(self):
        with open(self.input_tsv_file, 'r') as reader:
            tsv_reader = csv.DictReader(reader, delimiter='\t')
            tsv_entries = {}
            for line in tsv_reader:
                if line['index'] in tsv_entries:
                    sys.exit('Duplicate TSV indexes')
                tsv_entries[line['index']] = line
            return tsv_entries

    def min_match_count(self, peptide_length):
        return ceil(peptide_length / 2)

    def determine_consecutive_matches_from_left(self, mt_epitope_seq, wt_epitope_seq):
        consecutive_matches = 0
        for a, b in zip(mt_epitope_seq, wt_epitope_seq):
            if a == b:
                consecutive_matches += 1
            else:
                break
        return consecutive_matches

    def determine_consecutive_matches_from_right(self, mt_epitope_seq, wt_epitope_seq):
        consecutive_matches = 0
        for a, b in zip(reversed(mt_epitope_seq), reversed(wt_epitope_seq)):
            if a == b:
                consecutive_matches += 1
            else:
                break
        return consecutive_matches

    def determine_total_matches(self, mt_epitope_seq, wt_epitope_seq):
        matches = 0
        for a, b in zip(mt_epitope_seq, wt_epitope_seq):
            if a == b:
                matches += 1
        return matches

    def find_mutation_position(self, wt_epitope_seq, mt_epitope_seq):
        for i,(wt_aa,mt_aa) in enumerate(zip(wt_epitope_seq,mt_epitope_seq)):
            if wt_aa != mt_aa:
                return i+1
        return 0

    def match_wildtype_and_mutant_entry_for_missense(self, result, mt_position, wt_results, previous_result):
        #The WT epitope at the same position is the match
        match_position = mt_position
        mt_epitope_seq = result['mt_epitope_seq']
        wt_result      = wt_results[match_position]
        wt_epitope_seq = wt_result['wt_epitope_seq']
        result['wt_epitope_position'] = match_position
        total_matches  = self.determine_total_matches(mt_epitope_seq, wt_epitope_seq)
        if total_matches >= self.min_match_count(int(result['peptide_length'])):
            result['wt_epitope_seq'] = wt_epitope_seq
            result['wt_scores']      = wt_result['wt_scores']
        else:
            result['wt_epitope_seq'] = 'NA'
            result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')

        if mt_epitope_seq == wt_epitope_seq:
            result['mutation_position'] = 'NA'
        else:
            if previous_result:
                previous_mutation_position = previous_result['mutation_position']
                if previous_mutation_position == 'NA':
                    result['mutation_position'] = self.find_mutation_position(wt_epitope_seq, mt_epitope_seq)
                elif previous_mutation_position > 0:
                    result['mutation_position'] = previous_mutation_position - 1
                else:
                    result['mutation_position'] = 0
            else:
                result['mutation_position'] = self.find_mutation_position(wt_epitope_seq, mt_epitope_seq)

    def match_wildtype_and_mutant_entry_for_frameshift(self, result, mt_position, wt_results, previous_result):
        #The WT epitope at the same position is the match
        match_position = mt_position
        #Since the MT sequence is longer than the WT sequence, not all MT epitopes have a match
        if match_position not in wt_results:
            result['wt_epitope_seq'] = 'NA'
            result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')
            result['wt_epitope_position'] = 'NA'
            if previous_result['mutation_position'] == 'NA':
                result['mutation_position'] = 'NA'
            elif previous_result['mutation_position'] > 0:
                result['mutation_position'] = previous_result['mutation_position'] - 1
            else:
                result['mutation_position'] = 0
            return

        mt_epitope_seq = result['mt_epitope_seq']
        wt_result      = wt_results[match_position]
        wt_epitope_seq = wt_result['wt_epitope_seq']
        if mt_epitope_seq == wt_epitope_seq:
            #The MT epitope does not overlap the frameshift mutation
            result['wt_epitope_seq']    = wt_result['wt_epitope_seq']
            result['wt_scores']         = wt_result['wt_scores']
            result['mutation_position'] = 'NA'
            result['wt_epitope_position'] = 'NA'
        else:
            #Determine how many amino acids are the same between the MT epitope and its matching WT epitope
            total_matches = self.determine_total_matches(mt_epitope_seq, wt_epitope_seq)
            if total_matches >= self.min_match_count(int(result['peptide_length'])):
                #The minimum amino acid match count is met
                result['wt_epitope_seq'] = wt_result['wt_epitope_seq']
                result['wt_scores']      = wt_result['wt_scores']
            else:
                #The minimum amino acid match count is not met
                #Even though there is a matching WT epitope there are not enough overlapping amino acids
                #We don't include the matching WT epitope in the output
                result['wt_epitope_seq'] = 'NA'
                result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')
            mutation_position = self.find_mutation_position(wt_epitope_seq, mt_epitope_seq)
            if mutation_position == 1 and previous_result is not None and int(previous_result['mutation_position']) <= 1:
                #The true mutation position is to the left of the current MT eptiope
                mutation_position = 0
            result['mutation_position'] = mutation_position
            result['wt_epitope_position'] = match_position

    def match_wildtype_and_mutant_entry_for_inframe_indel(self, result, mt_position, wt_results, previous_result, iedb_results_for_wt_iedb_result_key):
        #If the previous WT epitope was matched "from the right" we can just use that position to infer the mutation position and match direction
        if previous_result is not None and previous_result['match_direction'] == 'right':
            best_match_position           = previous_result['wt_epitope_position'] + 1
            result['wt_epitope_position'] = best_match_position
            result['match_direction']     = 'right'
            if previous_result['mutation_position'] > 0:
                result['mutation_position'] = previous_result['mutation_position'] - 1
            else:
                result['mutation_position'] = 0

            #We need to ensure that the matched WT eptiope has enough overlapping amino acids with the MT epitope
            best_match_wt_result = wt_results[str(best_match_position)]
            total_matches        = self.determine_total_matches(result['mt_epitope_seq'], best_match_wt_result['wt_epitope_seq'])
            if total_matches and total_matches >= self.min_match_count(int(result['peptide_length'])):
                #The minimum amino acid match count is met
                result['wt_epitope_seq'] = best_match_wt_result['wt_epitope_seq']
                result['wt_scores']      = best_match_wt_result['wt_scores']
            else:
                #The minimum amino acid match count is not met
                #Even though there is a matching WT epitope there are not enough overlapping amino acids
                #We don't include the matching WT epitope in the output
                result['wt_epitope_seq'] = 'NA'
                result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')

            return

        #In all other cases the WT epitope at the same position is used as the baseline match
        baseline_best_match_position = mt_position

        #For an inframe insertion the MT sequence is longer than the WT sequence
        #In this case not all MT epitopes might have a baseline match
        if baseline_best_match_position not in wt_results:
            result['wt_epitope_seq'] = 'NA'
            result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')
            #We then infer the mutation position and match direction from the previous MT epitope
            result['match_direction']= previous_result['match_direction']
            if previous_result['mutation_position'] > 0:
                result['mutation_position'] = previous_result['mutation_position'] - 1
            else:
                result['mutation_position'] = 0
            return

        mt_epitope_seq = result['mt_epitope_seq']
        baseline_best_match_wt_result      = wt_results[baseline_best_match_position]
        baseline_best_match_wt_epitope_seq = baseline_best_match_wt_result['wt_epitope_seq']
        #The MT epitope does not overlap the indel mutation
        if baseline_best_match_wt_epitope_seq == mt_epitope_seq:
            result['wt_epitope_seq']      = baseline_best_match_wt_result['wt_epitope_seq']
            result['wt_scores']           = baseline_best_match_wt_result['wt_scores']
            result['wt_epitope_position'] = int(baseline_best_match_position)
            result['mutation_position']   = 'NA'
            result['match_direction']     = 'left'

        #If there is no previous result or the previous WT epitope was matched "from the left" we start by comparing to the baseline match
        if previous_result is None or previous_result['match_direction'] == 'left':
            best_match_count  = self.determine_consecutive_matches_from_left(mt_epitope_seq, baseline_best_match_wt_epitope_seq)
            #The alternate best match candidate "from the right" is inferred from the baseline best match position and the indel length
            if result['variant_type'] == 'inframe_ins':
                insertion_length              = len(iedb_results_for_wt_iedb_result_key.keys()) - len(wt_results.keys())
                alternate_best_match_position = int(baseline_best_match_position) - insertion_length
            elif result['variant_type'] == 'inframe_del':
                deletion_length                 = len(wt_results.keys()) - len(iedb_results_for_wt_iedb_result_key.keys())
                alternate_best_match_position   = int(baseline_best_match_position) + deletion_length
            if alternate_best_match_position > 0:
                alternate_best_match_wt_result      = wt_results[str(alternate_best_match_position)]
                alternate_best_match_wt_epitope_seq = alternate_best_match_wt_result['wt_epitope_seq']
                consecutive_matches_from_right      = self.determine_consecutive_matches_from_right(mt_epitope_seq, alternate_best_match_wt_epitope_seq)
                #We then check if the alternate best match epitope has more matching amino acids than the baseline best match epitope
                #If it does, we pick it as the best match
                if consecutive_matches_from_right > best_match_count:
                    match_direction      = 'right'
                    best_match_position  = alternate_best_match_position
                    best_match_wt_result = alternate_best_match_wt_result
                else:
                    match_direction      = 'left'
                    best_match_position  = baseline_best_match_position
                    best_match_wt_result = baseline_best_match_wt_result
            else:
                match_direction      = 'left'
                best_match_position  = baseline_best_match_position
                best_match_wt_result = baseline_best_match_wt_result

            #Now that we have found the matching WT epitope we still need to ensure that it has enough overlapping amino acids
            total_matches = self.determine_total_matches(mt_epitope_seq, best_match_wt_result['wt_epitope_seq'])
            if total_matches and total_matches >= self.min_match_count(int(result['peptide_length'])):
                #The minimum amino acid match count is met
                result['wt_epitope_seq'] = best_match_wt_result['wt_epitope_seq']
                result['wt_scores']      = best_match_wt_result['wt_scores']
            else:
                #The minimum amino acid match count is not met
                #Even though there is a matching WT epitope there are not enough overlapping amino acids
                #We don't include the matching WT epitope in the output
                result['wt_epitope_seq'] = 'NA'
                result['wt_scores']      = dict.fromkeys(result['mt_scores'].keys(), 'NA')

            result['mutation_position']   = self.find_mutation_position(baseline_best_match_wt_epitope_seq, mt_epitope_seq)
            result['match_direction']     = match_direction
            result['wt_epitope_position'] = best_match_position

    def match_wildtype_and_mutant_entries(self, iedb_results, wt_iedb_results):
        for key in sorted(iedb_results.keys(), key = lambda x: int(x.split('|')[-1])):
            result = iedb_results[key]
            (wt_iedb_result_key, mt_position) = key.split('|', 1)
            previous_mt_position = str(int(mt_position)-1)
            previous_key = '|'.join([wt_iedb_result_key, previous_mt_position])
            if previous_key in iedb_results:
                previous_result = iedb_results[previous_key]
            else:
                previous_result = None
            wt_results = wt_iedb_results[wt_iedb_result_key]
            if result['variant_type'] == 'missense':
                self.match_wildtype_and_mutant_entry_for_missense(result, mt_position, wt_results, previous_result)
            elif result['variant_type'] == 'FS':
                self.match_wildtype_and_mutant_entry_for_frameshift(result, mt_position, wt_results, previous_result)
            elif result['variant_type'] == 'inframe_ins' or result['variant_type'] == 'inframe_del':
                iedb_results_for_wt_iedb_result_key = dict([(key,value) for key, value in iedb_results.items() if key.startswith(wt_iedb_result_key)])
                self.match_wildtype_and_mutant_entry_for_inframe_indel(result, mt_position, wt_results, previous_result, iedb_results_for_wt_iedb_result_key)

        return iedb_results

    @abstractmethod
    def parse_iedb_file(self, tsv_entries):
        pass

    def add_summary_metrics(self, iedb_results):
        iedb_results_with_metrics = {}
        for key, value in iedb_results.items():
            mt_scores     = value['mt_scores']
            best_mt_score = sys.maxsize
            for method, score in mt_scores.items():
                if score < best_mt_score:
                    best_mt_score        = score
                    best_mt_score_method = method
            value['best_mt_score']          = best_mt_score
            value['corresponding_wt_score'] = value['wt_scores'][best_mt_score_method]
            value['best_mt_score_method']   = best_mt_score_method
            value['median_mt_score']        = median(mt_scores.values())
            wt_scores_with_value = [score for score in value['wt_scores'].values() if score != 'NA']
            if not wt_scores_with_value:
                value['median_wt_score']    = 'NA'
            else:
                value['median_wt_score']    = median(wt_scores_with_value)
            iedb_results_with_metrics[key]  = value

        return iedb_results_with_metrics

    def flatten_iedb_results(self, iedb_results):
        #transform the iedb_results dictionary into a two-dimensional list
        flattened_iedb_results = []
        for value in iedb_results.values():
            row = []
            for key in (
                'gene_name',
                'amino_acid_change',
                'position',
                'mutation_position',
                'mt_scores',
                'wt_scores',
                'wt_epitope_seq',
                'mt_epitope_seq',
                'tsv_index',
                'allele',
                'peptide_length',
                'best_mt_score',
                'corresponding_wt_score',
                'best_mt_score_method',
                'median_mt_score',
                'median_wt_score',
            ):
                if key in value.keys():
                    row.append(value[key])
                else:
                    row.append('NA')
            flattened_iedb_results.append(row)
        return flattened_iedb_results

    def process_input_iedb_file(self, tsv_entries):
        iedb_results = self.parse_iedb_file(tsv_entries)
        iedb_results_with_metrics = self.add_summary_metrics(iedb_results)
        flattened_iedb_results = self.flatten_iedb_results(iedb_results_with_metrics)

        return flattened_iedb_results

    def base_headers(self):
        headers = [
            'Chromosome',
            'Start',
            'Stop',
            'Reference',
            'Variant',
            'Transcript',
            'Transcript Support Level',
            'Ensembl Gene ID',
            'Variant Type',
            'Mutation',
            'Protein Position',
            'Gene Name',
            'HGVSc',
            'HGVSp',
            'HLA Allele',
            'Peptide Length',
            'Sub-peptide Position',
            'Mutation Position',
            'MT Epitope Seq',
            'WT Epitope Seq',
            'Best MT Score Method',
            'Best MT Score',
            'Corresponding WT Score',
            'Corresponding Fold Change',
            'Tumor DNA Depth',
            'Tumor DNA VAF',
            'Tumor RNA Depth',
            'Tumor RNA VAF',
            'Normal Depth',
            'Normal VAF',
            'Gene Expression',
            'Transcript Expression',
            'Median MT Score',
            'Median WT Score',
            'Median Fold Change',
        ]
        return headers

    def output_headers(self):
        headers = self.base_headers()
        for method in self.prediction_methods():
            pretty_method = PredictionClass.prediction_class_name_for_iedb_prediction_method(method)
            headers.append("%s WT Score" % pretty_method)
            headers.append("%s MT Score" % pretty_method)
        if self.sample_name:
            headers.append("Sample Name")

        return headers

    def prediction_methods(self):
        methods = set()
        for input_iedb_file in self.input_iedb_files:
            (sample, method, remainder) = os.path.basename(input_iedb_file).split(".", 2)
            methods.add(method)

        return sorted(list(methods))

    def execute(self):
        tsv_entries = self.parse_input_tsv_file()
        iedb_results = self.process_input_iedb_file(tsv_entries)

        tmp_output_file = self.output_file + '.tmp'
        tmp_output_filehandle = open(tmp_output_file, 'w')
        tsv_writer = csv.DictWriter(tmp_output_filehandle, delimiter='\t', fieldnames=self.output_headers())
        tsv_writer.writeheader()

        for (
            gene_name,
            variant_aa,
            position,
            mutation_position,
            mt_scores,
            wt_scores,
            wt_epitope_seq,
            mt_epitope_seq,
            tsv_index,
            allele,
            peptide_length,
            best_mt_score,
            corresponding_wt_score,
            best_mt_score_method,
            median_mt_score,
            median_wt_score
        ) in iedb_results:
            tsv_entry = tsv_entries[tsv_index]
            if mt_epitope_seq != wt_epitope_seq:
                if wt_epitope_seq == 'NA':
                    corresponding_fold_change = 'NA'
                elif best_mt_score == 0:
                    corresponding_fold_change = inf
                    corresponding_wt_score = round(corresponding_wt_score, 3)
                else:
                    corresponding_fold_change = round((corresponding_wt_score/best_mt_score), 3)
                    corresponding_wt_score = round(corresponding_wt_score, 3)
                if median_wt_score == 'NA':
                    median_fold_change = 'NA'
                elif median_mt_score == 0:
                    median_fold_change = inf
                    median_wt_score = round(median_wt_score, 3)
                else:
                    median_fold_change = round((median_wt_score/median_mt_score), 3)
                    median_wt_score = round(median_wt_score, 3)
                row = {
                    'Chromosome'          : tsv_entry['chromosome_name'],
                    'Start'               : tsv_entry['start'],
                    'Stop'                : tsv_entry['stop'],
                    'Reference'           : tsv_entry['reference'],
                    'Variant'             : tsv_entry['variant'],
                    'Transcript'          : tsv_entry['transcript_name'],
                    'Transcript Support Level': tsv_entry['transcript_support_level'],
                    'Ensembl Gene ID'     : tsv_entry['ensembl_gene_id'],
                    'HGVSc'               : tsv_entry['hgvsc'],
                    'HGVSp'               : tsv_entry['hgvsp'],
                    'Variant Type'        : tsv_entry['variant_type'],
                    'Mutation'            : variant_aa,
                    'Protein Position'    : tsv_entry['protein_position'],
                    'Gene Name'           : gene_name,
                    'HLA Allele'          : allele,
                    'Peptide Length'      : peptide_length,
                    'Sub-peptide Position': position,
                    'Mutation Position'   : mutation_position,
                    'MT Epitope Seq'      : mt_epitope_seq,
                    'WT Epitope Seq'      : wt_epitope_seq,
                    'Best MT Score Method': PredictionClass.prediction_class_name_for_iedb_prediction_method(best_mt_score_method),
                    'Best MT Score'       : round(best_mt_score, 3),
                    'Corresponding WT Score'    : corresponding_wt_score,
                    'Corresponding Fold Change' : corresponding_fold_change,
                    'Median MT Score'     : round(median_mt_score, 3),
                    'Median WT Score'     : median_wt_score,
                    'Median Fold Change'  : median_fold_change,
                }
                for method in self.prediction_methods():
                    pretty_method = PredictionClass.prediction_class_name_for_iedb_prediction_method(method)
                    if method in wt_scores:
                        row["%s WT Score" % pretty_method] = wt_scores[method]
                    else:
                        row["%s WT Score" % pretty_method] = 'NA'
                    if method in mt_scores:
                        row["%s MT Score" % pretty_method] = mt_scores[method]
                    else:
                        row["%s MT Score" % pretty_method] = 'NA'
                for (tsv_key, row_key) in zip(['gene_expression', 'transcript_expression', 'normal_vaf', 'tdna_vaf', 'trna_vaf'], ['Gene Expression', 'Transcript Expression', 'Normal VAF', 'Tumor DNA VAF', 'Tumor RNA VAF']):
                    if tsv_key in tsv_entry:
                        if tsv_entry[tsv_key] == 'NA':
                            row[row_key] = 'NA'
                        else:
                            row[row_key] = round(float(tsv_entry[tsv_key]), 3)
                for (tsv_key, row_key) in zip(['normal_depth', 'tdna_depth', 'trna_depth'], ['Normal Depth', 'Tumor DNA Depth', 'Tumor RNA Depth']):
                    if tsv_key in tsv_entry:
                        row[row_key] = tsv_entry[tsv_key]
                if self.sample_name:
                    row['Sample Name'] = self.sample_name
                tsv_writer.writerow(row)

        tmp_output_filehandle.close()
        os.replace(tmp_output_file, self.output_file)

class DefaultOutputParser(OutputParser):
    def parse_iedb_file(self, tsv_entries):
        with open(self.key_file, 'r') as key_file_reader:
            protein_identifiers_from_label = yaml.load(key_file_reader, Loader=yaml.FullLoader)
        iedb_results = {}
        wt_iedb_results = {}
        for input_iedb_file in self.input_iedb_files:
            with open(input_iedb_file, 'r') as reader:
                iedb_tsv_reader = csv.DictReader(reader, delimiter='\t')
                (sample, method, remainder) = os.path.basename(input_iedb_file).split(".", 2)
                for line in iedb_tsv_reader:
                    if "Warning: Potential DNA sequence(s)" in line['allele']:
                        continue
                    protein_label  = int(line['seq_num'])
                    if 'core_peptide' in line and int(line['end']) - int(line['start']) == 8:
                        #Start and end refer to the position of the core peptide
                        #Infer the (start) position of the peptide from the positions of the core peptide
                        position   = str(int(line['start']) - line['peptide'].find(line['core_peptide']))
                    else:
                        position   = line['start']
                    epitope        = line['peptide']
                    score          = line['ic50']
                    allele         = line['allele']
                    peptide_length = len(epitope)

                    if protein_identifiers_from_label[protein_label] is not None:
                        protein_identifiers = protein_identifiers_from_label[protein_label]

                    for protein_identifier in protein_identifiers:
                        (protein_type, tsv_index) = protein_identifier.split('.', 1)
                        if protein_type == 'MT':
                            tsv_entry = tsv_entries[tsv_index]
                            key = "%s|%s" % (tsv_index, position)
                            if key not in iedb_results:
                                iedb_results[key]                      = {}
                                iedb_results[key]['mt_scores']         = {}
                                iedb_results[key]['mt_epitope_seq']    = epitope
                                iedb_results[key]['gene_name']         = tsv_entry['gene_name']
                                iedb_results[key]['amino_acid_change'] = tsv_entry['amino_acid_change']
                                iedb_results[key]['variant_type']      = tsv_entry['variant_type']
                                iedb_results[key]['position']          = position
                                iedb_results[key]['tsv_index']         = tsv_index
                                iedb_results[key]['allele']            = allele
                                iedb_results[key]['peptide_length']    = peptide_length
                            iedb_results[key]['mt_scores'][method] = float(score)

                        results = {
                            'WT': wt_iedb_results,
                        }
                        if protein_type == 'MT':
                            continue
                        result_set = results[protein_type]
                        if tsv_index not in result_set:
                            result_set[tsv_index] = {}
                        if position not in result_set[tsv_index]:
                            result_set[tsv_index][position] = {}
                            result_set[tsv_index][position][protein_type.lower() + '_scores'] = {}
                        result_set[tsv_index][position][protein_type.lower() + '_epitope_seq'] = epitope
                        result_set[tsv_index][position][protein_type.lower() + '_scores'][method] = float(score)

        return self.match_wildtype_and_mutant_entries(iedb_results, wt_iedb_results)

class FusionOutputParser(OutputParser):
    def parse_iedb_file(self, tsv_entries):
        with open(self.key_file, 'r') as key_file_reader:
            tsv_indices_from_label = yaml.load(key_file_reader, Loader=yaml.FullLoader)
        iedb_results = {}
        for input_iedb_file in self.input_iedb_files:
            with open(input_iedb_file, 'r') as reader:
                iedb_tsv_reader = csv.DictReader(reader, delimiter='\t')
                (sample, method, remainder) = os.path.basename(input_iedb_file).split(".", 2)
                for line in iedb_tsv_reader:
                    if "Warning: Potential DNA sequence(s)" in line['allele']:
                        continue
                    protein_label  = int(line['seq_num'])
                    if 'core_peptide' in line:
                        position   = str(int(line['start']) - line['peptide'].find(line['core_peptide']))
                    else:
                        position   = line['start']
                    epitope        = line['peptide']
                    score          = line['ic50']
                    allele         = line['allele']
                    peptide_length = len(epitope)

                    if tsv_indices_from_label[protein_label] is not None:
                        tsv_indices = tsv_indices_from_label[protein_label]

                    for tsv_index in tsv_indices:
                        tsv_entry = tsv_entries[tsv_index]
                        key = "%s|%s" % (tsv_index, position)
                        if key not in iedb_results:
                            iedb_results[key]                      = {}
                            iedb_results[key]['mt_scores']         = {}
                            iedb_results[key]['wt_scores']         = {}
                            iedb_results[key]['mt_epitope_seq']    = epitope
                            iedb_results[key]['wt_epitope_seq']    = 'NA'
                            iedb_results[key]['gene_name']         = tsv_entry['gene_name']
                            iedb_results[key]['amino_acid_change'] = tsv_entry['amino_acid_change']
                            iedb_results[key]['variant_type']      = tsv_entry['variant_type']
                            iedb_results[key]['position']          = position
                            iedb_results[key]['tsv_index']         = tsv_index
                            iedb_results[key]['allele']            = allele
                            iedb_results[key]['peptide_length']    = peptide_length
                            iedb_results[key]['mutation_position'] = 'NA'
                        iedb_results[key]['mt_scores'][method] = float(score)
                        iedb_results[key]['wt_scores'][method] = 'NA'

        return iedb_results

class UnmatchedSequencesOutputParser(OutputParser):
    def parse_iedb_file(self):
        with open(self.key_file, 'r') as key_file_reader:
            tsv_indices_from_label = yaml.load(key_file_reader, Loader=yaml.FullLoader)
        iedb_results = {}
        for input_iedb_file in self.input_iedb_files:
            with open(input_iedb_file, 'r') as reader:
                iedb_tsv_reader = csv.DictReader(reader, delimiter='\t')
                (sample, method, remainder) = os.path.basename(input_iedb_file).split(".", 2)
                for line in iedb_tsv_reader:
                    if "Warning: Potential DNA sequence(s)" in line['allele']:
                        continue
                    protein_label  = int(line['seq_num'])
                    if 'core_peptide' in line:
                        position   = str(int(line['start']) - line['peptide'].find(line['core_peptide']))
                    else:
                        position   = line['start']
                    epitope        = line['peptide']
                    score          = line['ic50']
                    allele         = line['allele']
                    peptide_length = len(epitope)

                    if tsv_indices_from_label[protein_label] is not None:
                        tsv_indices = tsv_indices_from_label[protein_label]

                    for index in tsv_indices:
                        key = '|'.join([index, position])
                        if key not in iedb_results:
                            iedb_results[key]                      = {}
                            iedb_results[key]['mt_scores']         = {}
                            iedb_results[key]['mt_epitope_seq']    = epitope
                            iedb_results[key]['position']          = position
                            iedb_results[key]['tsv_index']         = index
                            iedb_results[key]['allele']            = allele
                        iedb_results[key]['mt_scores'][method] = float(score)
        return iedb_results

    def add_summary_metrics(self, iedb_results):
        iedb_results_with_metrics = {}
        for key, value in iedb_results.items():
            mt_scores     = value['mt_scores']
            best_mt_score = sys.maxsize
            for method, score in mt_scores.items():
                if score < best_mt_score:
                    best_mt_score        = score
                    best_mt_score_method = method
            value['best_mt_score']          = best_mt_score
            value['best_mt_score_method']   = best_mt_score_method
            value['median_mt_score']        = median(mt_scores.values())
            iedb_results_with_metrics[key]  = value
        return iedb_results_with_metrics

    def flatten_iedb_results(self, iedb_results):
        #transform the iedb_results dictionary into a two-dimensional list
        flattened_iedb_results = list((
            value['position'],
            value['mt_scores'],
            value['mt_epitope_seq'],
            value['tsv_index'],
            value['allele'],
            value['best_mt_score'],
            value['best_mt_score_method'],
            value['median_mt_score'],
        ) for value in iedb_results.values())
        return flattened_iedb_results

    def process_input_iedb_file(self):
        iedb_results              = self.parse_iedb_file()
        iedb_results_with_metrics = self.add_summary_metrics(iedb_results)
        flattened_iedb_results    = self.flatten_iedb_results(iedb_results_with_metrics)
        return flattened_iedb_results

    def base_headers(self):
        return[
            'Mutation',
            'HLA Allele',
            'Sub-peptide Position',
            'Epitope Seq',
            'Median Score',
            'Best Score',
            'Best Score Method',
        ]

    def output_headers(self):
        headers = self.base_headers()
        for method in self.prediction_methods():
            pretty_method = PredictionClass.prediction_class_name_for_iedb_prediction_method(method)
            headers.append("%s Score" % pretty_method)
        if self.sample_name:
            headers.append("Sample Name")
        return headers

    def execute(self):
        tmp_output_file = self.output_file + '.tmp'
        tmp_output_filehandle = open(tmp_output_file, 'w')
        tsv_writer = csv.DictWriter(tmp_output_filehandle, delimiter='\t', fieldnames=self.output_headers())
        tsv_writer.writeheader()

        iedb_results = self.process_input_iedb_file()
        for (
            position,
            mt_scores,
            mt_epitope_seq,
            tsv_index,
            allele,
            best_mt_score,
            best_mt_score_method,
            median_mt_score,
        ) in iedb_results:
            row = {
                'HLA Allele'          : allele,
                'Sub-peptide Position': position,
                'Epitope Seq'         : mt_epitope_seq,
                'Best Score Method'   : PredictionClass.prediction_class_name_for_iedb_prediction_method(best_mt_score_method),
                'Best Score'          : best_mt_score,
                'Median Score'        : round(median_mt_score, 3),
                'Mutation'            : tsv_index,
            }
            for method in self.prediction_methods():
                pretty_method = PredictionClass.prediction_class_name_for_iedb_prediction_method(method)
                if method in mt_scores:
                    row["%s Score" % pretty_method] = mt_scores[method]
                else:
                    row["%s Score" % pretty_method] = 'NA'
            tsv_writer.writerow(row)

        tmp_output_filehandle.close()
        os.replace(tmp_output_file, self.output_file)

