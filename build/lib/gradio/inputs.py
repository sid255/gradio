"""
This module defines various classes that can serve as the `input` to an interface. Each class must inherit from
`InputComponent`, and each class must define a path to its template. All of the subclasses of `InputComponent` are
automatically added to a registry, which allows them to be easily referenced in other parts of the code.
"""

import datetime
import json
import os
import time
import warnings
from gradio.component import Component
from gradio.embeddings import embed_text
import base64
import numpy as np
import PIL
from skimage.segmentation import slic
import scipy.io.wavfile
from gradio import processing_utils, test_data
import pandas as pd
import math
import tempfile
from pandas.api.types import is_bool_dtype, is_numeric_dtype, is_string_dtype


class InputComponent(Component):
    """
    Input Component. All input components subclass this.
    """
    def __init__(self, label):
        self.interpret()
        super().__init__(label)

    def preprocess(self, x):
        """
        Any preprocessing needed to be performed on function input.
        """
        return x

    def preprocess_example(self, x):
        """
        Any preprocessing needed to be performed on an example before being passed to the main function.
        """
        return x

    def interpret(self):
        '''
        Set any parameters for interpretation.
        '''
        return self

    def get_interpretation_neighbors(self, x):
        '''
        Generates values similar to input to be used to interpret the significance of the input in the final output.
        Parameters:
        x (Any): Input to interface
        Returns: (neighbor_values, interpret_kwargs, interpret_by_removal)
        neighbor_values (List[Any]): Neighboring values to input x to compute for interpretation
        interpret_kwargs (Dict[Any]): Keyword arguments to be passed to get_interpretation_scores
        interpret_by_removal (bool): If True, returned neighbors are values where the interpreted subsection was removed. If False, returned neighbors are values where the interpreted subsection was modified to a different value.
        '''
        pass

    def get_interpretation_scores(self, x, neighbors, scores, **kwargs):
        '''
        Arrange the output values from the neighbors into interpretation scores for the interface to render.
        Parameters:
        x (Any): Input to interface
        neighbors (List[Any]): Neighboring values to input x used for interpretation.
        scores (List[float]): Output value corresponding to each neighbor in neighbors
        kwargs (Dict[str, Any]): Any additional arguments passed from get_interpretation_neighbors.
        Returns:
        (List[Any]): Arrangement of interpretation scores for interfaces to render.
        '''
        pass

    def embed(self, x):
        """
        Return a default embedding for the *preprocessed* input to the interface. Used to compute similar inputs.
        x (Any): Input to interface
        Returns:
        (List[Float]): An embedding vector as a list or numpy array of floats
        """
        pass

class Textbox(InputComponent):
    """
    Component creates a textbox for user to enter input. Provides a string as an argument to the wrapped function.
    Input type: str
    """

    def __init__(self, lines=1, placeholder=None, default=None, numeric=False, type="str", label=None):
        """
        Parameters:
        lines (int): number of line rows to provide in textarea.
        placeholder (str): placeholder hint to provide behind textarea.
        default (str): default text to provide in textarea.
        numeric (bool): DEPRECATED. Whether the input should be parsed as a number instead of a string.        
        type (str): DEPRECATED. Type of value to be returned by component. "str" returns a string, "number" returns a float value. Use Number component in place of number type.
        label (str): component name in interface.
        """
        self.lines = lines
        self.placeholder = placeholder
        self.default = default
        if numeric or type == "number":
            warnings.warn("The 'numeric' type has been deprecated. Use the Number input component instead.", DeprecationWarning)
            self.type = "number"
        else:
            self.type = type
        if default is None:
            self.test_input = {
                "str": "the quick brown fox jumped over the lazy dog",
                "number": 786.92,
            }[type]
        else:
            self.test_input = default
        super().__init__(label)

    def get_template_context(self):
        return {
            "lines": self.lines,
            "placeholder": self.placeholder,
            "default": self.default,
            **super().get_template_context()
        }

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "text": {},
            "textbox": {"lines": 7},
        }

    def preprocess(self, x):
        if self.type == "str":
            return x
        elif self.type == "number":
            return float(x)
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'str', 'number'.")

    def preprocess_example(self, x):
        """
        Returns:
        (str): Text representing function input
        """
        return x

    def interpret(self, separator=" ", replacement=None):
        """
        Calculates interpretation score of characters in input by splitting input into tokens, then using a "leave one out" method to calculate the score of each token by removing each token and measuring the delta of the output value.
        Parameters:
        separator (str): Separator to use to split input into tokens.
        replacement (str): In the "leave one out" step, the text that the token should be replaced with.
        """
        self.interpretation_separator = separator
        self.interpretation_replacement = replacement
        return self
    
    def get_interpretation_neighbors(self, x):
        tokens = x.split(self.interpretation_separator)
        leave_one_out_strings = []
        for index in range(len(tokens)):
            leave_one_out_set = list(tokens)
            if self.interpretation_replacement is None:
                leave_one_out_set.pop(index)
            else:
                leave_one_out_set[index] = self.interpretation_replacement
            leave_one_out_strings.append(self.interpretation_separator.join(leave_one_out_set))
        return leave_one_out_strings, {"tokens": tokens}, True
    
    def get_interpretation_scores(self, x, neighbors, scores, tokens):
        """
        Returns:
        (List[Tuple[str, float]]): Each tuple set represents a set of characters and their corresponding interpretation score.
        """
        result = []
        for token, score in zip(tokens, scores):
            result.append((token, score))
            result.append((self.interpretation_separator, 0))
        return result

    def embed(self, x):
        """
        Embeds an arbitrary text based on word frequency
        """
        if self.type == "str":
            return embed_text(x)
        elif self.type == "number":
            return [float(x)]
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'str', 'number'.")


class Number(InputComponent):
    """
    Component creates a field for user to enter numeric input. Provides a nuber as an argument to the wrapped function.
    Input type: float
    """

    def __init__(self, default=None, label=None):
        '''
        Parameters:
        default (float): default value.
        label (str): component name in interface.
        '''
        self.default = default
        self.test_input = default if default is not None else 1
        super().__init__(label)

    def get_template_context(self):
        return {
            "default": self.default,
            **super().get_template_context()
        }

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "number": {},
        }

    def preprocess_example(self, x):
        """
        Returns:
        (float): Number representing function input
        """
        return x

    def interpret(self, steps=3, delta=1, delta_type="percent"):
        """
        Calculates interpretation scores of numeric values close to the input number.
        Parameters:
        steps (int): Number of nearby values to measure in each direction (above and below the input number).
        delta (float): Size of step in each direction between nearby values.
        delta_type (str): "percent" if delta step between nearby values should be a calculated as a percent, or "absolute" if delta should be a constant step change.
        """
        self.interpretation_steps = steps
        self.interpretation_delta = delta
        self.interpretation_delta_type = delta_type
        return self
        
    def get_interpretation_neighbors(self, x):
        neighbors = []
        if self.interpretation_delta_type == "percent":
            delta = 1.0 * self.interpretation_delta * x / 100
        elif self.interpretation_delta_type == "absolute":
            delta = self.interpretation_delta
        negatives = (x + np.arange(-self.interpretation_steps, 0) * delta).tolist()
        positives = (x + np.arange(1, self.interpretation_steps+1) * delta).tolist()
        return negatives + positives, {}, False

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (List[Tuple[float, float]]): Each tuple set represents a numeric value near the input and its corresponding interpretation score.
        """
        interpretation = list(zip(neighbors, scores))
        interpretation.insert(int(len(interpretation) / 2), [x, None])
        return interpretation

    def embed(self, x):
        return [float(x)]


class Slider(InputComponent):
    """
    Component creates a slider that ranges from `minimum` to `maximum`. Provides a number as an argument to the wrapped function.
    Input type: float
    """

    def __init__(self, minimum=0, maximum=100, step=None, default=None, label=None):
        '''
        Parameters:
        minimum (float): minimum value for slider.
        maximum (float): maximum value for slider.
        step (float): increment between slider values.
        default (float): default value.
        label (str): component name in interface.
        '''
        self.minimum = minimum
        self.maximum = maximum
        if step is None:
            difference = maximum - minimum
            power = math.floor(math.log10(difference) - 1)
            step = 10 ** power
        self.step = step
        self.default = minimum if default is None else default
        self.test_input = self.default
        super().__init__(label)

    def get_template_context(self):
        return {
            "minimum": self.minimum,
            "maximum": self.maximum,
            "step": self.step,
            "default": self.default,
            **super().get_template_context()
        }

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "slider": {},
        }

    def preprocess_example(self, x):
        """
        Returns:
        (float): Number representing function input
        """
        return x

    def interpret(self, steps=8):
        """
        Calculates interpretation scores of numeric values ranging between the minimum and maximum values of the slider.
        Parameters:
        steps (int): Number of neighboring values to measure between the minimum and maximum values of the slider range.
        """
        self.interpretation_steps = steps
        return self

    def get_interpretation_neighbors(self, x):
        return np.linspace(self.minimum, self.maximum, self.interpretation_steps).tolist(), {}, False

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (List[float]): Each value represents the score corresponding to an evenly spaced range of inputs between the minimum and maximum slider values.
        """
        return scores

    def embed(self, x):
        return [float(x)]



class Checkbox(InputComponent):
    """
    Component creates a checkbox that can be set to `True` or `False`. Provides a boolean as an argument to the wrapped function.
    Input type: bool
    """

    def __init__(self, label=None):
        """
        Parameters:
        label (str): component name in interface.
        """
        self.test_input = True
        super().__init__(label)

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "checkbox": {},
        }

    def preprocess_example(self, x):
        """
        Returns:
        (bool): Boolean representing function input
        """
        return x

    def interpret(self):
        """
        Calculates interpretation score of the input by comparing the output against the output when the input is the inverse boolean value of x.
        """
        return self

    def get_interpretation_neighbors(self, x):
        return [not x], {}, False

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (Tuple[float, float]): The first value represents the interpretation score if the input is False, and the second if the input is True.
        """
        if x:
            return scores[0], None
        else:
            return None, scores[0]

    def embed(self, x):
        return [float(x)]



class CheckboxGroup(InputComponent):
    """
    Component creates a set of checkboxes of which a subset can be selected. Provides a list of strings representing the selected choices as an argument to the wrapped function.
    Input type: Union[List[str], List[int]]
    """

    def __init__(self, choices, type="value", label=None):
        '''
        Parameters:
        choices (List[str]): list of options to select from.
        type (str): Type of value to be returned by component. "value" returns the list of strings of the choices selected, "index" returns the list of indicies of the choices selected.
        label (str): component name in interface.
        '''
        self.choices = choices
        self.type = type
        self.test_input = self.choices
        super().__init__(label)

    def get_template_context(self):
        return {
            "choices": self.choices,
            **super().get_template_context()
        }

    def preprocess(self, x):
        if self.type == "value":
            return x
        elif self.type == "index":
            return [self.choices.index(choice) for choice in x]
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")

    def interpret(self):
        """
        Calculates interpretation score of each choice in the input by comparing the output against the outputs when each choice in the input is independently either removed or added.
        """
        return self

    def get_interpretation_neighbors(self, x):
        leave_one_out_sets = []
        for choice in self.choices:
            leave_one_out_set = list(x)
            if choice in leave_one_out_set:
                leave_one_out_set.remove(choice)
            else:
                leave_one_out_set.append(choice)
            leave_one_out_sets.append(leave_one_out_set)
        return leave_one_out_sets, {}, False

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (List[Tuple[float, float]]): For each tuple in the list, the first value represents the interpretation score if the input is False, and the second if the input is True.
        """
        final_scores = []
        for choice, score in zip(self.choices, scores):
            if choice in x:
                score_set = [score, None]
            else:
                score_set = [None, score]
            final_scores.append(score_set)
        return final_scores

    def embed(self, x):
        if self.type == "value":
            return [choice in x for choice in self.choices]
        elif self.type == "index":
            return [index in x for index in range(len(choices))]
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")



class Radio(InputComponent):
    """
    Component creates a set of radio buttons of which only one can be selected. Provides string representing selected choice as an argument to the wrapped function.
    Input type: Union[str, int]
    """

    def __init__(self, choices, type="value", label=None):
        '''
        Parameters:
        choices (List[str]): list of options to select from.
        type (str): Type of value to be returned by component. "value" returns the string of the choice selected, "index" returns the index of the choice selected.
        label (str): component name in interface.
        '''
        self.choices = choices
        self.type = type
        self.test_input = self.choices[0]
        super().__init__(label)

    def get_template_context(self):
        return {
            "choices": self.choices,
            **super().get_template_context()
        }

    def preprocess(self, x):
        if self.type == "value":
            return x
        elif self.type == "index":
            return self.choices.index(x)
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")

    def interpret(self):
        """
        Calculates interpretation score of each choice by comparing the output against each of the outputs when alternative choices are selected.
        """
        return self

    def get_interpretation_neighbors(self, x):
        choices = list(self.choices)
        choices.remove(x)
        return choices, {}, False

    def get_interpretation_scores(self, x, neighbors, scores):        
        """
        Returns:
        (List[float]): Each value represents the interpretation score corresponding to each choice.
        """
        scores.insert(self.choices.index(x), None)
        return scores

    def embed(self, x):
        if self.type == "value":
            return [choice==x for choice in self.choices]
        elif self.type == "index":
            return [index==x for index in range(len(choices))]
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")


class Dropdown(InputComponent):
    """
    Component creates a dropdown of which only one can be selected. Provides string representing selected choice as an argument to the wrapped function.
    Input type: Union[str, int]
    """

    def __init__(self, choices, type="value", label=None):
        '''
        Parameters:
        choices (List[str]): list of options to select from.
        type (str): Type of value to be returned by component. "value" returns the string of the choice selected, "index" returns the index of the choice selected.
        label (str): component name in interface.
        '''
        self.choices = choices
        self.type = type
        self.test_input = self.choices[0]
        super().__init__(label)

    def get_template_context(self):
        return {
            "choices": self.choices,
            **super().get_template_context()
        }

    def preprocess(self, x):
        if self.type == "value":
            return x
        elif self.type == "index":
            return self.choices.index(x)
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")

    def interpret(self):
        """
        Calculates interpretation score of each choice by comparing the output against each of the outputs when alternative choices are selected.
        """
        return self

    def get_interpretation_neighbors(self, x):
        choices = list(self.choices)
        choices.remove(x)
        return choices, {}, False

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (List[float]): Each value represents the interpretation score corresponding to each choice.
        """
        scores.insert(self.choices.index(x), None)
        return scores

    def embed(self, x):
        if self.type == "value":
            return [choice==x for choice in self.choices]
        elif self.type == "index":
            return [index==x for index in range(len(choices))]
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'value', 'index'.")


class Image(InputComponent):
    """
    Component creates an image upload box with editing capabilities. 
    Input type: Union[numpy.array, PIL.Image, str]
    """

    def __init__(self, shape=None, image_mode='RGB', invert_colors=False, source="upload", tool="editor", type="numpy", label=None):
        '''
        Parameters:
        shape (Tuple[int, int]): (width, height) shape to crop and resize image to; if None, matches input image size.
        image_mode (str): "RGB" if color, or "L" if black and white.
        invert_colors (bool): whether to invert the image as a preprocessing step.
        source (str): Source of image. "upload" creates a box where user can drop an image file, "webcam" allows user to take snapshot from their webcam, "canvas" defaults to a white image that can be edited and drawn upon with tools.
        tool (str): Tools used for editing. "editor" allows a full screen editor, "select" provides a cropping and zoom tool.
        type (str): Type of value to be returned by component. "numpy" returns a numpy array with shape (width, height, 3) and values from 0 to 255, "pil" returns a PIL image object, "file" returns a temporary file object whose path can be retrieved by file_obj.name.
        label (str): component name in interface.
        '''
        self.shape = shape
        self.image_mode = image_mode
        self.source = source
        self.tool = tool
        self.type = type
        self.invert_colors = invert_colors
        self.test_input = test_data.BASE64_IMAGE
        super().__init__(label)

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "image": {},
            "webcam": {"source": "webcam"},
            "sketchpad": {"image_mode": "L", "source": "canvas", "shape": (28, 28), "invert_colors": True},
        }

    def get_template_context(self):
        return {
            "image_mode": self.image_mode,
            "shape": self.shape,
            "source": self.source,
            "tool": self.tool,
            **super().get_template_context()
        }

    def preprocess(self, x):
        im = processing_utils.decode_base64_to_image(x)
        fmt = im.format
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            im = im.convert(self.image_mode)
        if self.shape is not None:
            im = processing_utils.resize_and_crop(im, self.shape)
        if self.invert_colors:
            im = PIL.ImageOps.invert(im)
        if self.type == "pil":
            return im
        elif self.type == "numpy":
            return np.array(im)
        elif self.type == "file":
            file_obj = tempfile.NamedTemporaryFile(suffix="."+fmt)
            im.save(file_obj.name)
            return file_obj
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'numpy', 'pil', 'file'.")

    def preprocess_example(self, x):
        return processing_utils.encode_file_to_base64(x)

    def rebuild(self, dir, data):
        """
        Default rebuild method to decode a base64 image
        """
        im = processing_utils.decode_base64_to_image(data)
        timestamp = datetime.datetime.now()
        filename = f'input_{timestamp.strftime("%Y-%m-%d-%H-%M-%S")}.png'
        im.save(f'{dir}/{filename}', 'PNG')
        return filename

    def interpret(self, segments=16):
        """
        Calculates interpretation score of image subsections by splitting the image into subsections, then using a "leave one out" method to calculate the score of each subsection by whiting out the subsection and measuring the delta of the output value.
        Parameters:
        segments (int): Number of interpretation segments to split image into.
        """
        self.interpretation_segments = segments
        return self

    def get_interpretation_neighbors(self, x):
        x = processing_utils.decode_base64_to_image(x)
        if self.shape is not None:
            x = processing_utils.resize_and_crop(x, self.shape)
        image = np.array(x)
        segments_slic = slic(image, self.interpretation_segments, compactness=10, sigma=1)
        leave_one_out_tokens, masks = [], []
        replace_color = np.mean(image, axis=(0, 1))
        for (i, segVal) in enumerate(np.unique(segments_slic)):
            mask = segments_slic == segVal
            white_screen = np.copy(image)
            white_screen[segments_slic == segVal] = replace_color
            leave_one_out_tokens.append(
                processing_utils.encode_array_to_base64(white_screen))
            masks.append(mask)
        return leave_one_out_tokens, {"masks": masks}, True

    def get_interpretation_scores(self, x, neighbors, scores, masks):
        """
        Returns:
        (List[List[float]]): A 2D array representing the interpretation score of each pixel of the image.
        """
        x = processing_utils.decode_base64_to_image(x)
        if self.shape is not None:
            x = processing_utils.resize_and_crop(x, self.shape)
        x = np.array(x)
        output_scores = np.zeros((x.shape[0], x.shape[1]))

        for score, mask in zip(scores, masks):
            output_scores += score * mask

        max_val, min_val = np.max(output_scores), np.min(output_scores)
        if max_val > 0:
            output_scores = (output_scores - min_val) / (max_val - min_val)
        return output_scores.tolist()

    def embed(self, x):
        shape = (100, 100) if self.shape is None else self.shape  
        if self.type == "pil":
            im = x
        elif self.type == "numpy":
            im = PIL.Image.fromarray(x)
        elif self.type == "file":
            im = PIL.Image.open(x)
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'numpy', 'pil', 'file'.")
        im = processing_utils.resize_and_crop(im, (shape[0], shape[1]))
        return np.asarray(im).flatten()

class Audio(InputComponent):
    """
    Component accepts audio input files. 
    Input type: Union[Tuple[int, numpy.array], str, numpy.array]
    """

    def __init__(self, source="upload", type="numpy", label=None):
        """
        Parameters:
        source (str): Source of audio. "upload" creates a box where user can drop an audio file, "microphone" creates a microphone input.
        type (str): Type of value to be returned by component. "numpy" returns a 2-set tuple with an integer sample_rate and the data numpy.array of shape (samples, 2), "file" returns a temporary file object whose path can be retrieved by file_obj.name, "mfcc" returns the mfcc coefficients of the input audio.
        label (str): component name in interface.
        """
        self.source = source
        self.type = type
        self.test_input = test_data.BASE64_AUDIO
        super().__init__(label)

    def get_template_context(self):
        return {
            "source": self.source,
            **super().get_template_context()
        }

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "audio": {},
            "microphone": {"source": "microphone"}
        }

    def preprocess(self, x):
        """
        By default, no pre-processing is applied to a microphone input file
        """
        file_obj = processing_utils.decode_base64_to_file(x)
        if self.type == "file":
            return file_obj
        elif self.type == "numpy":
            return scipy.io.wavfile.read(file_obj.name)
        elif self.type == "mfcc":
            return processing_utils.generate_mfcc_features_from_audio_file(file_obj.name)

    def preprocess_example(self, x):
        return processing_utils.encode_file_to_base64(x, type="audio")

    def interpret(self, segments=8):
        """
        Calculates interpretation score of audio subsections by splitting the audio into subsections, then using a "leave one out" method to calculate the score of each subsection by removing the subsection and measuring the delta of the output value.
        Parameters:
        segments (int): Number of interpretation segments to split audio into.
        """
        self.interpretation_segments = segments
        return self
    
    def get_interpretation_neighbors(self, x):
        file_obj = processing_utils.decode_base64_to_file(x)
        x = scipy.io.wavfile.read(file_obj.name)
        sample_rate, data = x
        leave_one_out_sets = []
        duration = data.shape[0]
        boundaries = np.linspace(0, duration, self.interpretation_segments + 1).tolist()
        boundaries = [round(boundary) for boundary in boundaries]
        for index in range(len(boundaries) - 1):
            leave_one_out_data = np.copy(data)
            start, stop = boundaries[index], boundaries[index + 1]
            leave_one_out_data[start:stop] = 0
            file = tempfile.NamedTemporaryFile()
            scipy.io.wavfile.write(file, sample_rate, leave_one_out_data)                
            out_data = processing_utils.encode_file_to_base64(file.name, type="audio", ext="wav")
            leave_one_out_sets.append(out_data)
        return leave_one_out_sets, {}, True

    def get_interpretation_scores(self, x, neighbors, scores):
        """
        Returns:
        (List[float]): Each value represents the interpretation score corresponding to an evenly spaced subsection of audio.
        """
        return scores

    def embed(self, x):
        raise NotImplementedError("Audio doesn't currently support embeddings")


class File(InputComponent):
    """
    Component accepts generic file uploads.
    Input type: Union[str, bytes]
    """

    def __init__(self, type="file", label=None):
        '''
        Parameters:
        type (str): Type of value to be returned by component. "file" returns a temporary file object whose path can be retrieved by file_obj.name, "binary" returns an bytes object.
        label (str): component name in interface.
        '''
        self.type = type
        self.test_input = None
        super().__init__(label)

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "file": {},
        }

    def preprocess(self, x):
        name, data, is_local_example = x["name"], x["data"], x["is_local_example"]            
        if self.type == "file":
            if is_local_example:
                return open(name)
            else:
                return processing_utils.decode_base64_to_file(data)
        elif self.type == "bytes":
            if is_local_example:
                with open(name, "rb") as file_data:
                    return file_data.read()
            return processing_utils.decode_base64_to_binary(data)
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'file', 'bytes'.")

    def embed(self, x):
        raise NotImplementedError("File doesn't currently support embeddings")


class Dataframe(InputComponent):
    """
    Component accepts 2D input through a spreadsheet interface.
    Input type: Union[pandas.DataFrame, numpy.array, List[Union[str, float]], List[List[Union[str, float]]]]
    """

    def __init__(self, headers=None, row_count=3, col_count=3, datatype="str", type="pandas", label=None):
        """
        Parameters:
        headers (List[str]): Header names to dataframe.
        row_count (int): Limit number of rows for input.
        col_count (int): Limit number of columns for input. If equal to 1, return data will be one-dimensional. Ignored if `headers` is provided.
        datatype (Union[str, List[str]]): Datatype of values in sheet. Can be provided per column as a list of strings, or for the entire sheet as a single string. Valid datatypes are "str", "number", "bool", and "date".
        type (str): Type of value to be returned by component. "pandas" for pandas dataframe, "numpy" for numpy array, or "array" for a Python array.
        label (str): component name in interface.
        """
        self.headers = headers
        self.datatype = datatype
        self.row_count = row_count
        self.col_count = len(headers) if headers else col_count
        self.type = type
        sample_values = {"str": "abc", "number": 786, "bool": True, "date": "02/08/1993"}
        column_dtypes = [datatype]*self.col_count if isinstance(datatype, str) else datatype
        self.test_input = [[sample_values[c] for c in column_dtypes] for _ in range(row_count)]

        super().__init__(label)

    def get_template_context(self):
        return {
            "headers": self.headers,
            "datatype": self.datatype,
            "row_count": self.row_count,
            "col_count": self.col_count,
            **super().get_template_context()
        }

    @classmethod
    def get_shortcut_implementations(cls):
        return {
            "dataframe": {"type": "pandas"},
            "numpy": {"type": "numpy"},
            "matrix": {"type": "array"},
            "list": {"type": "array", "col_count": 1},
        }

    def preprocess(self, x):
        if self.type == "pandas":
            if self.headers:
                return pd.DataFrame(x, columns=self.headers)
            else:
                return pd.DataFrame(x)
        if self.col_count == 1:
            x = [row[0] for row in x]
        if self.type == "numpy":
            return np.array(x)
        elif self.type == "array":
            return x
        else:
            raise ValueError("Unknown type: " + str(self.type) + ". Please choose from: 'pandas', 'numpy', 'array'.")

    def interpret(self):
        """
        Calculates interpretation score of each cell in the Dataframe by using a "leave one out" method to calculate the score of each cell by removing the cell and measuring the delta of the output value.
        """
        return self

    def get_interpretation_neighbors(self, x):
        x = pd.DataFrame(x)
        leave_one_out_sets = []
        shape = x.shape
        for i in range(shape[0]):
            for j in range(shape[1]):
                scalar = x.iloc[i, j]
                leave_one_out_df = x.copy()
                if is_bool_dtype(scalar):
                    leave_one_out_df.iloc[i, j] = not scalar
                elif is_numeric_dtype(scalar):
                    leave_one_out_df.iloc[i, j] = 0
                elif is_string_dtype(scalar):
                    leave_one_out_df.iloc[i, j] = ""
                leave_one_out_sets.append(leave_one_out_df.values.tolist())
        return leave_one_out_sets, {"shape": x.shape}, True

    def get_interpretation_scores(self, x, neighbors, scores, shape):
        """
        Returns:
        (List[List[float]]): A 2D array where each value corrseponds to the interpretation score of each cell.
        """
        return np.array(scores).reshape((shape)).tolist()

    def embed(self, x):
        raise NotImplementedError("DataFrame doesn't currently support embeddings")


#######################
# DEPRECATED COMPONENTS
#######################

class Sketchpad(InputComponent):
    """
    DEPRECATED. Component creates a sketchpad for black and white illustration. Provides numpy array of shape `(width, height)` as an argument to the wrapped function.
    Input type: numpy.array
    """

    def __init__(self, shape=(28, 28), invert_colors=True,
                 flatten=False, label=None):
        '''
        Parameters:
        shape (Tuple[int, int]): shape to crop and resize image to.
        invert_colors (bool): whether to represent black as 1 and white as 0 in the numpy array.
        flatten (bool): whether to reshape the numpy array to a single dimension.
        label (str): component name in interface.
        '''
        warnings.warn("Sketchpad has been deprecated. Please use 'Image' component to generate a sketchpad. The string shorcut 'sketchpad' has been moved to the Image component.", DeprecationWarning)
        self.image_width = shape[0]
        self.image_height = shape[1]
        self.invert_colors = invert_colors
        self.flatten = flatten
        super().__init__(label)

    def preprocess(self, x):
        """
        Default preprocessing method for the SketchPad is to convert the sketch to black and white and resize 28x28
        """
        im_transparent = processing_utils.decode_base64_to_image(x)
        # Create a white background for the alpha channel
        im = PIL.Image.new("RGBA", im_transparent.size, "WHITE")
        im.paste(im_transparent, (0, 0), im_transparent)
        im = im.convert('L')
        if self.invert_colors:
            im = PIL.ImageOps.invert(im)
        im = im.resize((self.image_width, self.image_height))
        if self.flatten:
            array = np.array(im).flatten().reshape(
                1, self.image_width * self.image_height)
        else:
            array = np.array(im).flatten().reshape(
                1, self.image_width, self.image_height)
        return array

    def process_example(self, example):
        return processing_utils.encode_file_to_base64(example)

    def rebuild(self, dir, data):
        """
        Default rebuild method to decode a base64 image
        """
        im = processing_utils.decode_base64_to_image(data)
        timestamp = datetime.datetime.now()
        filename = f'input_{timestamp.strftime("%Y-%m-%d-%H-%M-%S")}.png'
        im.save(f'{dir}/{filename}', 'PNG')
        return filename


class Webcam(InputComponent):
    """
    DEPRECATED. Component creates a webcam for captured image input. Provides numpy array of shape `(width, height, 3)` as an argument to the wrapped function.
    Input type: numpy.array
    """

    def __init__(self, shape=(224, 224), label=None):
        '''
        Parameters:
        shape (Tuple[int, int]): shape to crop and resize image to.
        label (str): component name in interface.
        '''
        warnings.warn("Webcam has been deprecated. Please use 'Image' component to generate a webcam. The string shorcut 'webcam' has been moved to the Image component.", DeprecationWarning)
        self.image_width = shape[0]
        self.image_height = shape[1]
        self.num_channels = 3
        super().__init__(label)

    def preprocess(self, x):
        """
        Default preprocessing method for is to convert the picture to black and white and resize to be 48x48
        """
        im = processing_utils.decode_base64_to_image(x)
        im = im.convert('RGB')
        im = processing_utils.resize_and_crop(
            im, (self.image_width, self.image_height))
        return np.array(im)

    def rebuild(self, dir, data):
        """
        Default rebuild method to decode a base64 image
        """
        im = processing_utils.decode_base64_to_image(data)
        timestamp = datetime.datetime.now()
        filename = f'input_{timestamp.strftime("%Y-%m-%d-%H-%M-%S")}.png'
        im.save('{}/{}'.format(dir, filename), 'PNG')
        return filename


class Microphone(InputComponent):
    """
    DEPRECATED. Component creates a microphone element for audio inputs. 
    Input type: numpy.array
    """

    def __init__(self, preprocessing=None, label=None):
        '''
        Parameters:
        preprocessing (Union[str, Callable]): preprocessing to apply to input
        label (str): component name in interface.
        '''
        warnings.warn("Microphone has been deprecated. Please use 'Audio' component to generate a microphone. The string shorcut 'microphone' has been moved to the Audio component.", DeprecationWarning)
        super().__init__(label)
        if preprocessing is None or preprocessing == "mfcc":
            self.preprocessing = preprocessing
        else:
            raise ValueError(
                "unexpected value for preprocessing", preprocessing)

    def preprocess(self, x):
        """
        By default, no pre-processing is applied to a microphone input file
        """
        file_obj = processing_utils.decode_base64_to_file(x)
        if self.preprocessing == "mfcc":
            return processing_utils.generate_mfcc_features_from_audio_file(file_obj.name)
        _, signal = scipy.io.wavfile.read(file_obj.name)
        return signal


    def rebuild(self, dir, data):
        inp = data.split(';')[1].split(',')[1]
        wav_obj = base64.b64decode(inp)
        timestamp = datetime.datetime.now()
        filename = f'input_{timestamp.strftime("%Y-%m-%d-%H-%M-%S")}.wav'
        with open("{}/{}".format(dir, filename), "wb+") as f:
            f.write(wav_obj)
        return filename
