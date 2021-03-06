import pickle
import chianti
import lasagne
import logsystem
import dltools
import theano
import theano.tensor as T
import sys
import numpy as np

sys.setrecursionlimit(10000)

config = {
    "num_classes": # TODO: Fill in the number of classes here,
    "batch_size": 3,
    "sample_factor": 1,
    "validation_frequency": 500,
    "model_filename": "models/custom.npz",
    "log_filename": "logs/custom.log",
    "snapshot_frequency": 500,
    "base_channels": 48,
    "fr_channels": 32
}

########################################################################################################################
# Ask for the cityscapes path
########################################################################################################################

config["model_filename"] = dltools.utility.get_interactive_input(
    "Enter model filename",
    "cache/model_custom_filename.txt",
    config["model_filename"])

config["log_filename"] = dltools.utility.get_interactive_input(
    "Enter log filename",
    "cache/log_custom_filename.txt",
    config["log_filename"])

########################################################################################################################
# DEFINE THE NETWORK
########################################################################################################################

with dltools.utility.VerboseTimer("Define network"):
    # Define the theano variables
    input_var = T.ftensor4()

    builder = dltools.architectures.FRRNABuilder(
        base_channels=config["base_channels"],
        lanes=config["fr_channels"],
        multiplier=2,
        num_classes=config["num_classes"]
    )
    network = builder.build(
        input_var=input_var,
        #TODO: Fill in the correct image size|here|                           |here|
        input_shape=(config["batch_size"], 3, 1024 // config["sample_factor"], 2048 // config["sample_factor"]))

#######################################################################################################################
# LOAD MODEL
########################################################################################################################

with dltools.utility.VerboseTimer("Load model"):
    network.load_model(config["model_filename"])
    
########################################################################################################################
# DEFINE LOSS
########################################################################################################################

with dltools.utility.VerboseTimer("Define loss"):
    # Get the raw network outputs
    target_var = T.itensor3()

    # Get the original predictions back
    # Set deterministic=False if you want to train with batch norm enabled
    all_predictions, split_outputs, split_shapes = dltools.hybrid_training.get_split_outputs(network, deterministic=False)
    predictions = all_predictions[0]

    test_all_outputs = lasagne.layers.get_output(network.output_layers, deterministic=True)
    test_predictions = test_all_outputs[0]

    # Training classification loss (supervised)
    classification_loss = dltools.utility.bootstrapped_categorical_cross_entropy4d_loss(
        predictions,
        target_var,
        batch_size=config["batch_size"],
        multiplier=32)

    # Validation classification loss (supervised)
    test_classification_loss = dltools.utility.bootstrapped_categorical_cross_entropy4d_loss(
        test_predictions,
        target_var,
        batch_size=config["batch_size"],
        multiplier=32)

    loss = classification_loss

########################################################################################################################
# COMPILE THEANO TRAIN FUNCTIONS
########################################################################################################################

with dltools.utility.VerboseTimer("Compile update functions"):
    param_blocks, params = dltools.hybrid_training.split_params(network)
    forward_pass_fn, givens = dltools.hybrid_training.compile_forward_pass(split_outputs, split_shapes, [input_var, target_var])
    grad_fns = dltools.hybrid_training.compile_grad_functions(
        split_outputs,
        param_blocks,
        [input_var, target_var],
        loss,
        givens)

    # Optimization parameters
    learning_rate = T.fscalar()

    # Create the update function
    grad_vars = dltools.hybrid_training.get_gradient_variables(params)

    # Choose whatever optimizer you like
    updates = lasagne.updates.adam(grad_vars, params, learning_rate=learning_rate)
    #updates = lasagne.updates.sgd(grad_vars, params, learning_rate=learning_rate)

    update_fn = theano.function(
        inputs=[learning_rate] + grad_vars,
        updates=updates,
    )


    def compute_update(imgs, targets, update_counter):
        # Compute the learning rate
        lr = np.float32(1e-3)
        if update_counter > 45000:
            lr = np.float32(1e-4)
            
        # Compute all gradients
        forward_pass_fn(imgs, targets)
        loss, grads = dltools.hybrid_training.compute_grads(grad_fns, param_blocks, imgs, targets)
        update_fn(lr, *grads)
        return loss

########################################################################################################################
# COMPILE THEANO VAL FUNCTIONS
########################################################################################################################

with dltools.utility.VerboseTimer("Compile validation function"):
    val_fn = theano.function(
        inputs=[input_var, target_var],
        outputs=[T.argmax(test_predictions, axis=1), test_classification_loss]
    )

########################################################################################################################
# SET UP OPTIMIZER
########################################################################################################################

with dltools.utility.VerboseTimer("Optimize"):
    logger = logsystem.FileLogWriter(config["log_filename"])

    augmentors = [
        chianti.subsample_augmentor(config["sample_factor"]),
        chianti.translation_augmentor(30), 
        chianti.gamma_augmentor(0.05),
    ]

    # TODO: Create a list of tuples of the form (image path, annotation image path). 
    # i.e. the list should be list [(img1.png, img1_ann.png), (img1.png, img2_ann.png), ...]
    # In order for the library (in its current state) to load your annotations, they have to 
    # be converted to the right format. An annotation image is a single channel png image where
    # classes are indicated by consecutive integers starting from 0. A void label (i.e. a pixel 
    # that is not labelled) is indicated by the value 255. I will soon add some code to load annotations
    # from color images (e.g. PASCAL VOC, MS COCO). 
    images = 

    provider = chianti.DataProvider(
        iterator=chianti.random_iterator(images),
        batchsize=config["batch_size"],
        augmentors=augmentors
    )

    # TODO: Create a list of tuples of the form (image path, annotation image path). 
    # i.e. the list should be list [(img1.png, img1_ann.png), (img1.png, img2_ann.png), ...]
    # In order for the library (in its current state) to load your annotations, they have to 
    # be converted to the right format. An annotation image is a single channel png image where
    # classes are indicated by consecutive integers starting from 0. A void label (i.e. a pixel 
    # that is not labelled) is indicated by the value 255. I will soon add some code to load annotations
    # from color images (e.g. PASCAL VOC, MS COCO). 
    validation_images = 
    validation_provider = chianti.DataProvider(
        iterator=chianti.sequential_iterator(validation_images),
        batchsize=config["batch_size"],
        augmentors=[
            chianti.subsample_augmentor(config["sample_factor"]),
        ]
    )

    optimizer = dltools.optimizer.MiniBatchOptimizer(
        compute_update,
        provider,
        [
            dltools.hooks.SnapshotHook(config["model_filename"], network, frequency=config["snapshot_frequency"]),
            dltools.hooks.LoggingHook(logger),
            dltools.hooks.SegmentationValidationHook(
                val_fn,
                validation_provider,
                logger,
                frequency=config["validation_frequency"])
        ])
    optimizer.optimize()
