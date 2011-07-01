#!/usr/bin/python

#
# This source file is part of appleseed.
# Visit http://appleseedhq.net/ for additional information and resources.
#
# This software is released under the MIT license.
#
# Copyright (c) 2010-2011 Francois Beaune
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

# Settings.
VersionString = "1.0"

# Imports.
import glob
import os
import re
from subprocess import call
import sys
from xml.etree.ElementTree import ElementTree


#
# Utility functions.
#

NEWLINE_REGEX = r"[\r\n]+"

def fatal(message):
    print
    print("FATAL: " + message + ", aborting.")
    sys.exit(1)

def stable_unique(seq):
    seen = {}
    result = []
    for item in seq:
        if item in seen: continue
        seen[item] = 1
        result.append(item)
    return result

def load_file(file_path):
    try:
       file = open(file_path, "r")
       text = file.read()
       file.close()
       return text
    except IOError:
       fatal("failed to load file '" + file_path + "'")


#
# Manifest class.
#

class Manifest:
    def __init__(self, manifest_path):
        print "Loading manifest file '" + manifest_path + "'..."

        try:
            tree = ElementTree()
            tree.parse(manifest_path)
        except IOError:
            fatal("failed to load manifest file '" + manifest_path + "'")

        # Extract root path.
        self.input_root_path = tree.find("input").attrib["root"]

        # Extract the list of input files.
        self.input_file_paths = []
        for file_element in tree.findall("input/file"):
            file_mask = os.path.join(self.input_root_path, file_element.text)
            self.input_file_paths.extend(glob.glob(file_mask))

        # Extract the output base path.
        self.output_base_path = tree.find("output/base_path").text

        # Extract header.
        self.header = tree.find("output/header").text

        # Extract the additional strings to strip.
        self.literals_to_strip = []
        self.regexes_to_strip = []
        for strip_element in tree.findall("output/strip"):
            if strip_element.attrib["type"] == "literal":
                self.literals_to_strip.append(strip_element.text)
            else:
                self.regexes_to_strip.append(strip_element.text)

        # Extract the command line to test-compile the output source file.
        self.test_command_line = tree.find("test/commandline").text

    def get_output_header_file_path(self):
        return self.output_base_path + ".h"

    def get_output_source_file_path(self):
        return self.output_base_path + ".cpp"


#
# DependencyFinder class.
#

class DependencyFinder:
    def __init__(self, manifest):
        self.manifest = manifest

    def gather_header_files(self):
        files = []

        for file_path in self.manifest.input_file_paths:
            if os.path.splitext(file_path)[1].lower() == ".h":
                files.extend(self.__gather_recursive_user_deps(file_path))

        for i in range(len(files)):
            files[i] = files[i].replace('\\', '/')

        return stable_unique(files)

    def gather_source_files(self):
        files = []

        for file_path in self.manifest.input_file_paths:
            if os.path.splitext(file_path)[1].lower() == ".cpp":
                files.append(file_path)

        for i in range(len(files)):
            files[i] = files[i].replace('\\', '/')

        return files

    def gather_platform_deps(self, header_files):
        deps = []

        for file_path in header_files:
            deps.extend(self.__gather_immediate_platform_deps(file_path))

        deps.sort()

        return stable_unique(deps)

    def __gather_recursive_user_deps(self, file_path):
        deps = []

        for sub_dep in self.__gather_immediate_user_deps(file_path):
            sub_dep_file_path = os.path.join(self.manifest.input_root_path, sub_dep)
            deps.extend(self.__gather_recursive_user_deps(sub_dep_file_path))

        deps.append(file_path)

        return deps

    def __gather_immediate_user_deps(self, file_path):
        return self.__gather_immediate_deps(file_path, r"\"", r"\"")

    def __gather_immediate_platform_deps(self, file_path):
        return self.__gather_immediate_deps(file_path, r"<", r">")

    def __gather_immediate_deps(self, file_path, opening_marker, closing_marker):
        text = load_file(file_path)

        deps = []
        pattern = re.compile(r"^#include " + opening_marker +
                             r"(?P<include_path>[^" + closing_marker + r"]*)" +
                             closing_marker + r"[^$]*$")

        for line in text.splitlines():
            match = pattern.search(line)
            if match:
                deps.append(match.group("include_path"))

        return deps


#
# FileGenerator class.
#

class FileGenerator:
    def __init__(self, manifest, depfinder):
        self.manifest = manifest
        self.depfinder = depfinder

    def generate_output_header_file(self):
        output_file_path = self.manifest.get_output_header_file_path()
        print "Generating '" + output_file_path + "'..."

        header_files = self.depfinder.gather_header_files()

        output_file = open(output_file_path, "w")

        # Write header.
        output_file.write(self.manifest.header)

        # Generate the header guard.
        header_guard_token = os.path.basename(output_file_path).replace("/", "_").replace("\\", "_").replace(".", "_").upper()
        output_file.write("#ifndef " + header_guard_token + "\n")
        output_file.write("#define " + header_guard_token + "\n\n")

        # Include all the platform headers.
        platform_deps = self.depfinder.gather_platform_deps(header_files)
        if len(platform_deps) > 0:
            output_file.write("// Standard and platform headers.\n")
            for dep in platform_deps:
                output_file.write("#include <" + dep + ">\n")
            output_file.write("\n")

        # Concatenate the content of all header files.
        self.__write_files(output_file, header_files)

        # Close the header guard.
        output_file.write("#endif  // !" + header_guard_token + "\n")

        output_file.close()

    def generate_output_source_file(self):
        output_file_path = self.manifest.get_output_source_file_path()
        print "Generating '" + output_file_path + "'..."

        source_files = self.depfinder.gather_source_files()

        output_file = open(output_file_path, "w")

        # Write header.
        output_file.write(self.manifest.header)

        # Include the header file.
        output_file.write("// Interface header.\n")
        output_file.write("#include \"" + os.path.basename(self.manifest.output_base_path) + ".h\"\n\n")

        # Include all the platform headers.
        platform_deps = self.depfinder.gather_platform_deps(source_files)
        if len(platform_deps) > 0:
            output_file.write("// Standard and platform headers.\n")
            for dep in platform_deps:
                output_file.write("#include <" + dep + ">\n")
            output_file.write("\n")

        # Concatenate the content of all source files.
        self.__write_files(output_file, source_files)

        output_file.close()

    def __write_files(self, output_file, input_file_paths):
        for input_file_path in input_file_paths:
            text = load_file(input_file_path)
            text = self.__strip_dependencies(text)
            text = self.__strip_custom_literals(text)
            text = self.__strip_custom_regexes(text)
            output_file.write(text)

    def __strip_dependencies(self, text):
        return re.sub(r"^#include .*" + NEWLINE_REGEX, "", text, 0, re.MULTILINE)

    def __strip_custom_literals(self, text):
        for literal in self.manifest.literals_to_strip:
            text = text.replace(literal, "")
        return text

    def __strip_custom_regexes(self, text):
        for regex in self.manifest.regexes_to_strip:
            text = re.sub(regex, "", text, 0, re.MULTILINE)
        return text


#
# Tester class.
#

class Tester:
    def __init__(self, manifest):
        self.manifest = manifest

    def compile(self, file_path):
        print "Test-compiling '" + file_path + "'...\n"
        call(self.manifest.test_command_line.replace("$cppfile", file_path), shell=True)


#
# Entry point.
#

def main():
    print "appleseed.gather version " + VersionString
    
    if len(sys.argv) < 2:
        print "Usage: " + sys.argv[0] + " manifest.xml"
        sys.exit(1)

    manifest = Manifest(sys.argv[1])
    depfinder = DependencyFinder(manifest)

    filegen = FileGenerator(manifest, depfinder)
    filegen.generate_output_header_file()
    filegen.generate_output_source_file()

    if len(manifest.test_command_line) > 0:
        tester = Tester(manifest)
        tester.compile(manifest.get_output_source_file_path())

main()
