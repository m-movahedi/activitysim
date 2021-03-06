# ActivitySim
# See full license in LICENSE.txt.

import logging

import pandas as pd

from activitysim.core.simulate import read_model_spec
from activitysim.core.interaction_simulate import interaction_simulate

from activitysim.core import tracing
from activitysim.core import config
from activitysim.core import inject
from activitysim.core import pipeline

from .util import expressions
from activitysim.core.util import assign_in_place
from .util.tour_destination import tour_destination_size_terms

logger = logging.getLogger(__name__)


@inject.injectable()
def non_mandatory_tour_destination_spec(configs_dir):
    return read_model_spec(configs_dir, 'non_mandatory_tour_destination_sample.csv')


@inject.step()
def non_mandatory_tour_destination(
        tours,
        persons_merged,
        skim_dict,
        non_mandatory_tour_destination_spec,
        land_use, size_terms,
        chunk_size,
        trace_hh_id):

    """
    Given the tour generation from the above, each tour needs to have a
    destination, so in this case tours are the choosers (with the associated
    person that's making the tour)
    """

    trace_label = 'non_mandatory_tour_destination'
    model_settings = config.read_model_settings('non_mandatory_tour_destination.yaml')

    tours = tours.to_frame()

    persons_merged = persons_merged.to_frame()
    alternatives = tour_destination_size_terms(land_use, size_terms, 'non_mandatory')
    spec = non_mandatory_tour_destination_spec

    # choosers are tours - in a sense tours are choosing their destination
    non_mandatory_tours = tours[tours.tour_category == 'non_mandatory']

    # - if no mandatory_tours
    if non_mandatory_tours.shape[0] == 0:
        tracing.no_results(trace_label)
        return

    # FIXME - don't need all persons_merged columns...
    choosers = pd.merge(non_mandatory_tours, persons_merged, left_on='person_id', right_index=True)

    constants = config.get_model_constants(model_settings)

    sample_size = model_settings["SAMPLE_SIZE"]

    # create wrapper with keys for this lookup - in this case there is a TAZ in the choosers
    # and a TAZ in the alternatives which get merged during interaction
    # interaction_dataset adds '_r' suffix to duplicate columns,
    # so TAZ column from households is TAZ and TAZ column from alternatives becomes TAZ_r
    skims = skim_dict.wrap("TAZ", "TAZ_r")

    locals_d = {
        'skims': skims
    }
    if constants is not None:
        locals_d.update(constants)

    logger.info("Running non_mandatory_tour_destination_choice with %d non_mandatory_tours" %
                len(choosers.index))

    choices_list = []
    # segment by trip type and pick the right spec for each person type
    for name, segment in choosers.groupby('tour_type'):

        # FIXME - there are two options here escort with kids and without
        kludge_name = name
        if name == "escort":
            logging.error("destination_choice escort not implemented - running shopping instead")
            kludge_name = "shopping"

        # the segment is now available to switch between size terms
        locals_d['segment'] = kludge_name

        # FIXME - no point in considering impossible alternatives (where dest size term is zero)
        alternatives_segment = alternatives[alternatives[kludge_name] > 0]

        logger.info("Running segment '%s' of %d tours %d alternatives" %
                    (name, len(segment), len(alternatives_segment)))

        # name index so tracing knows how to slice
        assert segment.index.name == 'tour_id'

        choices = interaction_simulate(
            segment,
            alternatives_segment,
            spec[[kludge_name]],
            skims=skims,
            locals_d=locals_d,
            sample_size=sample_size,
            chunk_size=chunk_size,
            trace_label=tracing.extend_trace_label(trace_label,  name))

        choices_list.append(choices)

    choices = pd.concat(choices_list)

    non_mandatory_tours['destination'] = choices

    assign_in_place(tours, non_mandatory_tours[['destination']])

    pipeline.replace_table("tours", tours)

    if trace_hh_id:
        tracing.trace_df(tours[tours.tour_category == 'non_mandatory'],
                         label="non_mandatory_tour_destination",
                         slicer='person_id',
                         index_label='tour',
                         columns=None,
                         warn_if_empty=True)
