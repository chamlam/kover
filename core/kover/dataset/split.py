#!/usr/bin/env python
"""
	Kover: Learn interpretable computational phenotyping models from k-merized genomic data
	Copyright (C) 2015  Alexandre Drouin

	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import logging
import numpy as np

from h5py.h5f import ACC_RDWR
from math import ceil

from ..dataset import KoverDataset
from ..learning.set_covering_machine.rules import KmerRuleClassifications
from ..utils import _hdf5_open_no_chunk_cache, _minimum_uint_size


def split_with_ids(input, split_name, train_ids, test_ids, random_seed, n_folds, warning_callback=None,
                   error_callback=None, progress_callback=None):

    # Execution callback functions
    if warning_callback is None:
        warning_callback = lambda w: logging.warning(w)
    if error_callback is None:
        def normal_raise(exception):
            raise exception
        error_callback = normal_raise
    if progress_callback is None:
        progress_callback = lambda p, m: None

    random_generator = np.random.RandomState(random_seed)

    dataset = KoverDataset(input)
    idx_by_genome_id = dict(zip(dataset.genome_identifiers[...], range(dataset.genome_count)))

    # Validate that the genome identifiers refer to genomes in the dataset
    not_in_ds = []
    for id in train_ids:
        if id not in idx_by_genome_id:
            not_in_ds.append(id)
    if len(not_in_ds) > 0:
        error_callback(Exception("The training genome identifiers contain IDs that are not in the dataset: %s" %
                                 ", ".join(not_in_ds)))
    not_in_ds = []
    for id in test_ids:
        if id not in idx_by_genome_id:
            not_in_ds.append(id)
    if len(not_in_ds) > 0:
        error_callback(Exception("The testing genome identifiers contain IDs that are not in the dataset: %s" %
                                 ", ".join(not_in_ds)))

    # Get the idx of the genome ids
    train_idx = [idx_by_genome_id[id] for id in train_ids]
    test_idx = [idx_by_genome_id[id] for id in test_ids]

    _split(dataset=dataset, split_name=split_name, train_idx=train_idx, test_idx=test_idx,
           random_generator=random_generator, random_seed=random_seed, n_folds=n_folds,
           warning_callback=warning_callback, error_callback=error_callback, progress_callback=progress_callback)


def split_with_proportion(input, split_name, train_prop, undersampling, cut_test, random_seed, n_folds, warning_callback=None, error_callback=None,
                          progress_callback=None):
    
    # Execution callback functions
    if warning_callback is None:
        warning_callback = lambda w: logging.warning(w)
    if error_callback is None:
        def normal_raise(exception):
            raise exception
        error_callback = normal_raise
    if progress_callback is None:
        progress_callback = lambda p, m: None

    random_generator = np.random.RandomState(random_seed)

    dataset = KoverDataset(input)

    # Randomly split the genome indexes into a training and testing set
    n_genomes = dataset.genome_count
    idx = None
    maj_sample_size = 0
    train_idx = None
    test_idx = None
    
    # Normal case
    if (undersampling == 0.0):
        idx = np.arange(n_genomes)
        n_train = int(ceil(train_prop * n_genomes))
        random_generator.shuffle(idx)
        train_idx = idx[:n_train]
        test_idx = idx[n_train:]
        
    # With undersampling of the majority class
    else:
        metadata = np.array((dataset.phenotype).metadata)
        idx_dict = {'positive' :(np.where(metadata))[0],
                    'negative' : (np.where(metadata == 0))[0] }
                    
        # Finding the minority and majority class
        min_class = 'positive'
        maj_class = 'negative'
        if(idx_dict['positive'].shape[0] > idx_dict['negative'].shape[0]):
            min_class = 'negative'
            maj_class = 'positive'
        
        # Undersampling the majority class by choosing a restricted number of examples idx of this class
        maj_class_size = idx_dict[maj_class].shape[0]
        min_class_size = idx_dict[min_class].shape[0]
        if (int(ceil(min_class_size*undersampling)) > maj_class_size):
            warning_callback("Undersampling is greater than majority class size, split will be unaffected")
            idx = np.arange(n_genomes)
        else :
            maj_sample_size = int(ceil(min_class_size*undersampling))
            if(not(cut_test)):
                random_generator.shuffle(idx_dict[maj_class])
                idx = np.append(((idx_dict[maj_class])[:maj_sample_size]),(idx_dict[min_class]))
                n_genomes = idx.shape[0]
                n_train = int(ceil(train_prop * n_genomes))
                random_generator.shuffle(idx)
                train_idx = idx[:n_train]
                test_idx = idx[n_train:]
                test_idx = np.append(test_idx, (idx_dict[maj_class])[maj_sample_size:])
            else:
                idx = np.arange(n_genomes)
                n_train = int(ceil(train_prop * n_genomes))
                random_generator.shuffle(idx)
                train_idx = (idx[:n_train]).tolist()
                test_idx = idx[n_train:]
                train_size = int(ceil((train_prop * (maj_sample_size + min_class_size))))
                maj_class_to_del = len(train_idx) - train_size
                maj_ids = idx_dict[maj_class].tolist()
                min_ids = idx_dict[min_class].tolist()
                i = 0
                del_list = []
                while(maj_class_to_del != 0):
                    if train_idx[i] in maj_ids:
                        del_list.append(train_idx[i])
                        maj_class_to_del -= 1
                    i += 1
                train_idx = [i for i in train_idx if i not in del_list]

    _split(dataset=dataset, split_name=split_name, train_idx=train_idx, test_idx=test_idx,
           random_generator=random_generator, random_seed=random_seed, n_folds=n_folds,
           warning_callback=warning_callback, error_callback=error_callback, progress_callback=progress_callback)


def _split(dataset, split_name, random_generator, random_seed, train_idx, test_idx, warning_callback,
           error_callback, progress_callback, n_folds=0):
    # Execution callback functions
    if warning_callback is None:
        warning_callback = lambda w: logging.warning(w)
    if error_callback is None:
        def normal_raise(exception):
            raise exception
        error_callback = normal_raise
    if progress_callback is None:
        progress_callback = lambda p, m: None

    _validate_split(dataset, split_name, train_idx, test_idx, n_folds, warning_callback, error_callback)

    train_idx = np.array(train_idx)
    test_idx = np.array(test_idx)

    dataset_hdf5 = dataset.dataset_open(ACC_RDWR)  # The hdf5 file of the dataset, use dataset for high-level operations

    if len(dataset.splits) == 0:
        dataset_hdf5.create_group("splits")

    splits = dataset_hdf5["splits"]
    split = splits.create_group(split_name)
    split.attrs["random_seed"] = random_seed
    split.attrs["n_folds"] = n_folds
    split.attrs["train_proportion"] = 1.0 * len(train_idx) / dataset.genome_count
    split.attrs["test_proportion"] = 1.0 * len(test_idx) / dataset.genome_count

    # for progress
    n_splits_done = 0
    n_splits_to_perform = 1 + n_folds

    # Create the training and testing sets
    logging.debug("Splitting the genomes into a training set and a testing set.")
    example_idx_dtype = _minimum_uint_size(dataset.genome_count)
    split.create_dataset("train_genome_idx", data=np.sort(train_idx), dtype=example_idx_dtype)
    split.create_dataset("test_genome_idx", data=np.sort(test_idx), dtype=example_idx_dtype)
    n_splits_done += 0.5
    progress_callback("Split", 1.0 * n_splits_done / n_splits_to_perform)

    # Compute the kmer individual risks (store only a pointer to unique values [rounded at 5 decimals])
    logging.debug("Computing the k-mer individual risks.")
    labels = dataset.phenotype.metadata[...]
    train_pos_idx = train_idx[labels[train_idx] == 1]
    train_neg_idx = train_idx[labels[train_idx] == 0]
    kmer_matrix = KmerRuleClassifications(dataset.kmer_matrix, len(labels))
    # XXX: In the following 2 lines, we trim the result of sum_rows to keep only the presence rule classifications.
    kmer_risks = (len(train_pos_idx) - kmer_matrix.sum_rows(train_pos_idx)[: dataset.kmer_count]).astype(np.float)  # n positive errors
    kmer_risks += kmer_matrix.sum_rows(train_neg_idx)[: dataset.kmer_count]  # n negative errors
    kmer_risks /= len(train_idx)  # n examples
    np.round(kmer_risks, 5, out=kmer_risks)
    anti_kmer_risks = 1.0 - kmer_risks
    np.round(anti_kmer_risks, 5, out=anti_kmer_risks)
    unique_risks, unique_risk_by_kmer_and_antikmer = np.unique(np.hstack((kmer_risks, anti_kmer_risks)), return_inverse=True)
    del kmer_risks, anti_kmer_risks
    split.create_dataset("unique_risks", data=unique_risks)
    split.create_dataset("unique_risk_by_kmer", data=unique_risk_by_kmer_and_antikmer[:dataset.kmer_count], dtype=_minimum_uint_size(len(unique_risks)))
    split.create_dataset("unique_risk_by_anti_kmer", data=unique_risk_by_kmer_and_antikmer[dataset.kmer_count:], dtype=_minimum_uint_size(len(unique_risks)))

    n_splits_done += 0.5
    progress_callback("Split", 1.0 * n_splits_done / n_splits_to_perform)

    if n_folds > 0:
        logging.debug("Splitting the training set into %d cross-validation folds." % n_folds)
        folds = split.create_group("folds")

        # Assign each genome to a fold randomly
        fold_by_training_set_genome = np.arange(len(train_idx)) % n_folds
        random_generator.shuffle(fold_by_training_set_genome)

        for fold in xrange(n_folds):
            logging.debug("Fold %d" % (fold + 1))

            fold_group = folds.create_group("fold_%d" % (fold + 1))

            fold_train_idx = train_idx[fold_by_training_set_genome != fold]
            fold_test_idx = train_idx[fold_by_training_set_genome == fold]
            fold_group.create_dataset("train_genome_idx", data=np.sort(fold_train_idx), dtype=example_idx_dtype)
            fold_group.create_dataset("test_genome_idx", data=np.sort(fold_test_idx), dtype=example_idx_dtype)
            n_splits_done += 0.5
            progress_callback("Split", 1.0 * n_splits_done / n_splits_to_perform)

            # Compute the kmer individual risks (store only a pointer to unique values [rounded at 5 decimals])
            logging.debug("Computing the k-mer individual risks.")
            fold_train_pos_idx = fold_train_idx[labels[fold_train_idx] == 1]
            fold_train_neg_idx = fold_train_idx[labels[fold_train_idx] == 0]
            # XXX: In the following 2 lines, we trim the result of sum_rows to keep only the presence rule classifications.
            kmer_risks = (len(fold_train_pos_idx) - kmer_matrix.sum_rows(fold_train_pos_idx)[: dataset.kmer_count]).astype(np.float)  # n positive errors
            kmer_risks += kmer_matrix.sum_rows(fold_train_neg_idx)[: dataset.kmer_count]  # n negative errors
            kmer_risks /= len(fold_train_idx)  # n examples
            np.round(kmer_risks, 5, out=kmer_risks)
            anti_kmer_risks = 1.0 - kmer_risks
            np.round(anti_kmer_risks, 5, out=anti_kmer_risks)
            unique_risks, unique_risk_by_kmer_and_antikmer = np.unique(np.hstack((kmer_risks, anti_kmer_risks)), return_inverse=True)
            del kmer_risks, anti_kmer_risks
            fold_group.create_dataset("unique_risks", data=unique_risks)
            fold_group.create_dataset("unique_risk_by_kmer", data=unique_risk_by_kmer_and_antikmer[:dataset.kmer_count], dtype=_minimum_uint_size(len(unique_risks)))
            fold_group.create_dataset("unique_risk_by_anti_kmer", data=unique_risk_by_kmer_and_antikmer[dataset.kmer_count:], dtype=_minimum_uint_size(len(unique_risks)))

            n_splits_done += 0.5
            progress_callback("Split", 1.0 * n_splits_done / n_splits_to_perform)


def _validate_split(dataset, split_name, train_idx, test_idx, n_folds, warning_callback, error_callback):
    if dataset.phenotype.name == "NA":
        error_callback(Exception("A dataset must contain phenotypic metadata to be split."))

    if split_name in (split.name for split in dataset.splits):
        error_callback(Exception("A split with the identifier \"%s\" already exists in the dataset." % split_name))

    if n_folds > len(train_idx):
        error_callback(Exception("There cannot be more cross-validation folds (%d) than genomes in the training set"
                                     " (%d)." % (n_folds, len(train_idx))))

    if n_folds == 1:
        error_callback(Exception("The number of cross-validation folds must be greater than 1."))

    # Verify that there are no duplicates in each list
    if len(set(train_idx)) < len(train_idx):
        error_callback(Exception("The training set contains duplicate genomes."))
    if len(set(test_idx)) < len(test_idx):
        error_callback(Exception("The testing set contains duplicate genomes."))

    # Verify that there is no overlap between the training and testing ids
    if len(set(train_idx).union(test_idx)) < len(train_idx) + len(test_idx):
        error_callback(Exception("The training and testing set overlap."))
