import os
import sys
import typing as T

import requests
from hydrus.utils import cli_request_api_key, verify_permissions
from hydrus import Permission, Client, APIError, ImportStatus, FileMetadataResultType, TagAction

USED_PERMISSIONS = [Permission.AddTags, Permission.SearchFiles, Permission.ImportFiles]
DATA_FILE_LOCATION = os.path.abspath("..\data_file.png") # relative to the working folder
# noinspection SpellCheckingInspection
DATA_FILE_HASH = "90fe21b9b91523620ed32feeb6608087f3190393a613774c22b3f381b21431b2"
TAG_THIS_FILE_TAG = "tagscore meta:score me"
DATA_FILE_UNIQUE_TAG = "tagscore meta:data file"
TAG_SCORE_NAMESPACE = "tagscore tag score"
TAG_REPO_NAME = "my tags"


class TagscoreClient(Client):
    # not a huge fan of this but this list may get super big so this may be good or it won't be worth it also possible.
    tag_score_tags: T.Optional[T.List[str]] = None
    
    tag_scores: T.Optional[T.Dict[str, int]] = None
    
    def has_data_file(self) -> bool:
        return self.get_data_file() is not None
    
    def get_data_file(self) -> T.Optional[requests.Response]:
        try:
            return self.get_file(hash_=DATA_FILE_HASH)
        except APIError:
            return None
        
    def add_data_file(self) -> None:
        """
        Adds the data file to client, also prints error codes to the user, only returns when successful
        :return: Only when successful. In all other cases the function exits the program.
        """
        responses = self.add_and_tag_files(paths_and_files=[DATA_FILE_LOCATION], tags=[DATA_FILE_UNIQUE_TAG])
        assert len(responses) == 1
        response = responses[0]
        status = response.get("status")
        if status == ImportStatus.Success or status == ImportStatus.Exists:
            return
        elif status == ImportStatus.PreviouslyDeleted: 
            print("The tagscore data file was previously deleted.\n"
                  "Please remove the deletion record for the data file and try again.\n"
                  "The easiest way to do this is to import the data file by hand, see it fail, "
                  "go to the file import status, press the right mouse button on the file import, "
                  "press the try again option, and then answer yes when the client asks you if you "
                  "want to remove deletion records for that file.\n"
                  "You can find the data file here: " + DATA_FILE_LOCATION)
            sys.exit(1)
        elif status == ImportStatus.Failed:
            print("The tagscore data file failed to import. Please resolve this error and try again:\n" + 
                  response.get("note"))
            sys.exit(1)
        elif status == ImportStatus.Vetoed:
            print("The tagscore data file failed to import due to an import veto. \n"
                  "This often means that you have import settings in the clients import settings (options -> importing)"
                  "that prevent the data file from importing.\n"
                  "Please remove these preventions and try again.\n"
                  "You can find the data file here: " + DATA_FILE_LOCATION)
            sys.exit(1)
        else:
            print("The tagscore data file failed to import due to an unknown issue.\n"
                  "Please try updating tagscore or resolving the following issue (if exists):\n" + 
                  response.get("note"))
            sys.exit(1)
            
    def get_to_score_file_list(self) -> T.List[int]:
        return self.search_files([TAG_THIS_FILE_TAG])

    def has_files_to_be_scored(self) -> bool:
        file_list = self.get_to_score_file_list()
        return len(file_list) > 0

    def set_tag_score_tags(self):
        self.tag_score_tags = list(filter(lambda el: el != DATA_FILE_UNIQUE_TAG, self.get_data_file_tags()))

    def has_tag_scores(self) -> bool:
        assert self.tag_score_tags is not None
        # we assume that the file exists since the control flow requires this.
        return len(self.tag_score_tags) > 0

    def get_data_file_metadata(self) -> FileMetadataResultType:
        return self.file_metadata(hashes=[DATA_FILE_HASH])
    
    def get_data_file_tags(self) -> T.List[str]:
        for file_metadata in self.get_data_file_metadata():
            if file_metadata["hash"] == DATA_FILE_HASH:
                # noinspection PyTypeChecker
                my_tags: T.Dict[str, T.List[str]] = file_metadata["service_names_to_statuses_to_tags"][TAG_REPO_NAME]
                return my_tags["0"] # TODO: fix this type when we have 3.9 installed.
        assert False # here we assume the file to exist

    def has_malformed_tags(self) -> bool:
        assert self.tag_score_tags is not None
        found_invalid = False
        for tag in self.tag_score_tags:
            if not is_valid_score_tag(tag):
                found_invalid = True
        return found_invalid

    def score_files(self):
        self.tag_scores = {}
        for tag in self.tag_score_tags:
            tag_sections = tag.split(":")
            self.tag_scores[":".join(tag_sections[1:len(tag_sections) -1])] = int(tag_sections[len(tag_sections) - 1])
        
        to_tag_file_ids = self.search_files([TAG_THIS_FILE_TAG])
        # noinspection SpellCheckingInspection
        file_metadatas = self.file_metadata(file_ids=to_tag_file_ids)
        
        hash_to_current_score_tag: T.Dict[str, T.Optional[str]] = {}
        
        hash_to_score: T.Dict[str, int] = {}
        lowest = 0
        for file_metadata in file_metadatas:
            # save current score for removal
            # noinspection PyTypeChecker
            hash_to_current_score_tag[file_metadata["hash"]] = get_current_score_tag_for_tags(file_metadata["service_names_to_statuses_to_tags"]["all known tags"]["0"])
            # get new score
            # noinspection PyTypeChecker
            new_score = self._get_score_for_tags(file_metadata["service_names_to_statuses_to_tags"]["all known tags"]["0"])
            if new_score < lowest:
                lowest = new_score
            hash_to_score[file_metadata["hash"]] = new_score
        if lowest != 0:
            for file_hash, score in hash_to_score.items():
                hash_to_score[file_hash] = score + lowest
        for file_hash, score in hash_to_score.items():
            self.add_tags(hashes=[file_hash], service_to_action_to_tags={TAG_REPO_NAME:{TagAction.Delete:[str(hash_to_current_score_tag[file_hash])]}})
            self.add_tags(hashes=[file_hash], service_to_tags={TAG_REPO_NAME: [TAG_SCORE_NAMESPACE + ":" + str(score)]})

    def _get_score_for_tags(self, tags: T.List[str]) -> int:
        score = 0
        total_scored_tags = 0
        
        for tag in tags:
            to_add = self.tag_scores.get(tag)
            if to_add is not None:
                score += to_add
                total_scored_tags += 1
        
        return score if score == 0 else score / total_scored_tags

def get_current_score_tag_for_tags(tags: T.List[str]) -> T.Optional[str]:
    for tag in tags:
        if tag.startswith(TAG_SCORE_NAMESPACE + ":"):
            return tag
    return None


def is_valid_score_tag(tag: str) -> bool:
    tag_sections = tag.split(":")
    if len(tag_sections) < 3:
        # we need at least the namespace, the tag, and the score
        print(f"Found invalid tag score tag with reason: Not enough data (did you forget the tag or the score?): '{tag}'")
        return False
    if tag_sections[0] != TAG_SCORE_NAMESPACE:
        print(f"Found invalid tag score tag with reason: Wrong namespace: '{tag}'")
        return False
    try:
        int(tag_sections[len(tag_sections) -1])
    except ValueError:
        print(f"Found invalid tag score tag with reason: Score is not an integer: '{tag}'")
        return False
    return True

def print_scoring_help():
    print("Scoring with tagscore help:\n"
          "The data file:\n"
          "In order to save scores per tag in the client tagscore adds a data file to the client.\n"
          "To find this data file it will be given the tag "
          "This data file will carry the scored that tags have. Using this manner of saving data makes tagscore "
          "removable and easily transferable.\n"
          "Just transfer the data file with its tags to a new client and you are on your way again. \n"
          f"This file will be given the following tag: {DATA_FILE_UNIQUE_TAG}.\n\n"
          "Tagging files for scoring:\n"
          "In order to ensure that the user fully controls what files are scored tagscore will only score files"
          f"that have the tag: '{TAG_THIS_FILE_TAG}'.\n"
          "(You can hide this namespace from appearing visibly in the client via the client's options if you want.)\n\n"
          "Scoring tags:\n"
          "Tagscore uses the tagscore data file to save tag scores as tag in the client. "
          "To score a tag you add it to the data file as such:\n"
          f"{TAG_SCORE_NAMESPACE}:namespace:tag:score\n"
          "Where score is a positive or negative integer. "
          "For tags without namespace you leave out the namespace and the first colon.\n\n"
          "Examples:\n"
          "You want to give the tag 'test' a score of +10: \n"
          f"{TAG_SCORE_NAMESPACE}:test:10\n"
          "You want to give the tag 'test' a score of -10: \n"
          f"{TAG_SCORE_NAMESPACE}:test:-10\n"
          "You want to give the tag 'character:queen elsa of arendelle' a score of +200: \n"
          f"{TAG_SCORE_NAMESPACE}:character:queen elsa of arendelle:200\n"
          "You want to give the tag 'character:queen elsa of arendelle' a score of -200: \n"
          "You may not do this, Elsa deserves a high score.\n"
          "You want to give the tag 'tag:with:colons' a score of 0: \n"
          f"{TAG_SCORE_NAMESPACE}:with:colons:0")


def main(client: TagscoreClient):
    if not client.has_data_file():
        client.add_data_file()
    # we now know for sure that the client has the data file.
    # the next step is to see of the user has set any files to be scored.
    if not client.has_files_to_be_scored():
        print("Detected no files to be scored. Please tag some files to be scored and try again.")
        print_scoring_help()
        sys.exit(0)
    # We know that the client wants to score files and has files to be scored
    # we now check if the client has any tag scores set up.
    client.set_tag_score_tags()
    if client.has_malformed_tags():
        print("Found malformed score tags on the data file. Try removing or fixing these tags.")
        print("If one or more of these tags are not actually malformed "
              "please contact the tagscore developer (matjojo) on the hydrus discord.")
        sys.exit(0)

    if not client.has_tag_scores():
        print("Did not find any tag scores. Please set up some tag scores and try again.")
        print_scoring_help()
        sys.exit(0)
    # we know now that the client wants to score files and has files to be scored and has tag scores set up.
    client.score_files()
    sys.exit(0)
    
    
    
        
if __name__ == "__main__":
    try:
        with open("access_key") as access_key_file:
            read_key = access_key_file.readline()
            new_client = TagscoreClient(read_key)
            if not verify_permissions(client=new_client, permissions=USED_PERMISSIONS):
                print("tagscore does not have the proper permissions,"
                      "try deleting the tagscore api service and setting the service up again."
                      "(This will not remove any of the saved scores.)")
                os.remove("access_key")
                sys.exit(1)
            main(new_client)
            
    except OSError: # file not found
        new_key = cli_request_api_key("tagscore", USED_PERMISSIONS)
        try:
            with open("access_key", mode="w") as access_key_file:
                access_key_file.write(new_key)
                main(TagscoreClient(new_key))
                sys.exit(0)
        except OSError:
            print("Could not save access key to file.")
            sys.exit(1)
    