# The user wants: "Category selection: When a /release query is sent prompt the user to select which category to search in with all category as an option as well. The current category includes (Movies, TV, XXX, Audio, Books, PC, Console, Others) with all category option at the bottom. This list is configurable using /settings where the owner can disable desired categories and this new /settings is expandable for future settings. This category selection shouldn't work for /release iMDBid only for queries."
#
# Jackett categories in Torznab:
# Movies = 2000
# TV = 5000
# Audio = 3000
# PC = 4000
# Console = 1000
# XXX = 6000
# Books = 7000, 8000
# Others = 8000, etc.
# Actually I can just map standard torznab categories to these:
# Movies: 2000
# TV: 5000
# XXX: 6000
# Audio: 3000
# Books: 7000
# PC: 4000
# Console: 1000
# Others: 8000

# "Tag selection: After selecting a category prompt the user to select a tag from jackett inside jackett for any set tags for an index or tracker fetch them and show them as options here to select one. With all tags at the bottom. Tags can accept /release iMDBid meaning someone sending an imdbid will be prompted to select a tag."

# How to fetch tags from Jackett?
# You can hit the /api/v2.0/indexers/all/results/torznab/api?apikey=...&t=indexers to get indexers and their tags, then aggregate the tags!
